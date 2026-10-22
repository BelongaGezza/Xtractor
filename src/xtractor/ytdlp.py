"""yt-dlp adapter: the ONLY module allowed to import ``yt_dlp``.

``yt_dlp`` is imported lazily so that ``-h``/``--version`` stay fast and work without it.
Every exception leaving this module has been classified by ``errors.classify_exception``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import InternalError, XtractorError, classify_exception
from .formats import MediaInfo
from .tools import JsRuntime
from .urls import VideoRef

OUTTMPL = "%(id)s.%(ext)s"
RETRIES = 3
SOCKET_TIMEOUT = 30
MAX_BACKOFF = 30


@dataclass(frozen=True)
class Progress:
    """A download progress event passed to the ``on_progress`` callback."""

    downloaded_bytes: int
    total_bytes: int | None
    speed: float | None  # bytes/s
    eta: int | None  # seconds
    status: str  # "downloading" | "finished"


class Extractor(Protocol):
    def probe(self, ref: VideoRef) -> MediaInfo:
        """Fetch metadata and the format list without downloading anything."""
        ...

    def download(
        self,
        ref: VideoRef,
        format_selector: str,
        dest_dir: Path,
        outtmpl: str,
        merge_to: str | None,
        on_progress: Callable[[Progress], None],
    ) -> Path:
        """Download ``format_selector`` into ``dest_dir`` and return the file path."""
        ...


class LogSink(Protocol):
    def debug(self, message: str) -> None: ...


def backoff(attempt: int) -> float:
    """Exponential backoff in seconds: 1, 2, 4, ... capped at 30 (``attempt`` starts at 0)."""
    return float(min(2 ** max(attempt, 0), MAX_BACKOFF))


class StderrLogger:
    """yt-dlp ``logger`` routing everything through the Reporter (debug only if verbose)."""

    def __init__(self, sink: LogSink) -> None:
        self._sink = sink

    def debug(self, msg: str) -> None:
        self._sink.debug(msg)

    def info(self, msg: str) -> None:
        self._sink.debug(msg)

    def warning(self, msg: str) -> None:
        self._sink.debug(f"yt-dlp warning: {msg}")

    def error(self, msg: str) -> None:
        self._sink.debug(f"yt-dlp error: {msg}")


def base_params(
    *,
    dest_dir: Path | None = None,
    outtmpl: str = OUTTMPL,
    ffmpeg_location: Path | None = None,
    js_runtime: JsRuntime | None = None,
    logger: object | None = None,
    progress_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
) -> dict[str, Any]:
    """The single place where ``YoutubeDL`` options are defined (plan 2.4).

    No cookies, credentials, DRM options or ``allow_unplayable_formats``.
    """
    params: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": RETRIES,
        "fragment_retries": RETRIES,
        "extractor_retries": RETRIES,
        "file_access_retries": RETRIES,
        "socket_timeout": SOCKET_TIMEOUT,
        "retry_sleep_functions": {
            "http": backoff,
            "fragment": backoff,
            "extractor": backoff,
            "file_access": backoff,
        },
        "continuedl": True,
        "nopart": False,
        "overwrites": False,
        "windowsfilenames": True,
        "outtmpl": outtmpl,
        "no_color": True,
    }
    if logger is not None:
        params["logger"] = logger
    if dest_dir is not None:
        params["paths"] = {"home": str(dest_dir), "temp": str(dest_dir)}
    if progress_hooks:
        params["progress_hooks"] = progress_hooks
    if ffmpeg_location is not None:
        params["ffmpeg_location"] = str(ffmpeg_location)
    if js_runtime is not None:
        params["js_runtimes"] = {js_runtime.name: {"path": str(js_runtime.path)}}
    return params


def progress_from_hook(d: Mapping[str, Any]) -> Progress:
    """Convert a yt-dlp progress-hook dict into a :class:`Progress`."""

    def num(key: str) -> float | None:
        v = d.get(key)
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    total = num("total_bytes") or num("total_bytes_estimate")
    eta = num("eta")
    return Progress(
        downloaded_bytes=int(num("downloaded_bytes") or 0),
        total_bytes=int(total) if total else None,
        speed=num("speed"),
        eta=int(eta) if eta is not None else None,
        status="finished" if d.get("status") == "finished" else "downloading",
    )


def find_downloaded(info: Mapping[str, Any], dest_dir: Path) -> Path | None:
    """Locate the final file of a finished download from yt-dlp's result (or by scanning)."""
    for item in info.get("requested_downloads") or []:
        fp = item.get("filepath")
        if fp and Path(fp).is_file():
            return Path(fp)
    fp = info.get("filepath") or info.get("_filename")
    if fp and Path(fp).is_file():
        return Path(fp)
    vid = str(info.get("id") or "")
    candidates = [
        p
        for p in sorted(dest_dir.glob(f"{vid}.*" if vid else "*"))
        if p.is_file() and p.suffix not in (".part", ".ytdl")
    ]
    return candidates[-1] if candidates else None


class YtDlpExtractor:
    """Real extractor backed by ``yt_dlp.YoutubeDL``."""

    def __init__(
        self,
        *,
        ffmpeg_location: Path | None = None,
        js_runtime: JsRuntime | None = None,
        logger: LogSink | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg_location
        self._js = js_runtime
        self._logger = StderrLogger(logger) if logger is not None else None

    def _youtube_dl(self, params: dict[str, Any]) -> Any:
        import yt_dlp  # lazy: keeps -h/--version fast and dependency-free

        return yt_dlp.YoutubeDL(params)

    def probe(self, ref: VideoRef) -> MediaInfo:
        params = base_params(ffmpeg_location=self._ffmpeg, js_runtime=self._js, logger=self._logger)
        try:
            with self._youtube_dl(params) as ydl:
                info = ydl.extract_info(ref.canonical_url, download=False)
        except XtractorError:
            raise
        except Exception as exc:
            raise classify_exception(exc, video_id=ref.video_id) from exc
        if not isinstance(info, dict):
            raise InternalError(f"no metadata returned for {ref.video_id}")
        if info.get("_type") == "playlist":  # defensive: noplaylist should prevent this
            entries = [e for e in info.get("entries") or [] if e]
            if not entries:
                raise InternalError(f"no metadata returned for {ref.video_id}")
            info = entries[0]
        return MediaInfo.from_dict(info)

    def download(
        self,
        ref: VideoRef,
        format_selector: str,
        dest_dir: Path,
        outtmpl: str,
        merge_to: str | None,
        on_progress: Callable[[Progress], None],
    ) -> Path:
        def hook(d: dict[str, Any]) -> None:
            on_progress(progress_from_hook(d))

        params = base_params(
            dest_dir=dest_dir,
            outtmpl=outtmpl,
            ffmpeg_location=self._ffmpeg,
            js_runtime=self._js,
            logger=self._logger,
            progress_hooks=[hook],
        )
        params["format"] = format_selector
        if merge_to:
            params["merge_output_format"] = merge_to
            params["postprocessors"] = [{"key": "FFmpegMetadata", "add_metadata": True}]
        try:
            with self._youtube_dl(params) as ydl:
                info = ydl.extract_info(ref.canonical_url, download=True)
        except XtractorError:
            raise
        except Exception as exc:
            raise classify_exception(exc, video_id=ref.video_id) from exc
        path = find_downloaded(info if isinstance(info, dict) else {}, dest_dir)
        if path is None:
            raise InternalError(f"download finished but no file was found for {ref.video_id}")
        return path
