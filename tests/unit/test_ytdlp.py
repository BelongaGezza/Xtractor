from __future__ import annotations

import errno
from pathlib import Path
from typing import Any, ClassVar

import pytest

from tests.unit.fixtures import AAC_441
from xtractor.errors import (
    FileSystemError,
    InternalError,
    MissingDependency,
    NetworkError,
    VideoUnavailable,
    XtractorError,
)
from xtractor.tools import JsRuntime
from xtractor.urls import parse_youtube_url
from xtractor.ytdlp import (
    StderrLogger,
    YtDlpExtractor,
    backoff,
    base_params,
    find_downloaded,
    progress_from_hook,
)

REF = parse_youtube_url("https://youtu.be/dQw4w9WgXcQ")
JS = JsRuntime("deno", Path("/opt/bin/deno"))

INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "T",
    "uploader": "U",
    "formats": [
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "asr": 44100}
    ],
}


class FakeDL:
    """Stands in for yt_dlp.YoutubeDL; records params and the extract_info call."""

    instances: ClassVar[list[FakeDL]] = []

    def __init__(self, params: dict[str, Any], result: Any = None, exc: Exception | None = None):
        self.params = params
        self.result = result
        self.exc = exc
        self.calls: list[tuple[str, bool]] = []
        FakeDL.instances.append(self)

    def __enter__(self) -> FakeDL:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> Any:
        self.calls.append((url, download))
        if self.exc is not None:
            raise self.exc
        return self.result


class Extractor(YtDlpExtractor):
    result: Any = INFO
    exc: Exception | None = None

    def _youtube_dl(self, params: dict[str, Any]) -> Any:
        return FakeDL(params, self.result, self.exc)


# ------------------------------------------------------------ params (T4.2)
def test_base_params_values() -> None:
    p = base_params(dest_dir=Path("/t"), ffmpeg_location=Path("/f/ffmpeg"), js_runtime=JS)
    assert p["retries"] == p["fragment_retries"] == p["extractor_retries"] == 3
    assert p["noplaylist"] is True and p["continuedl"] is True and p["nopart"] is False
    assert p["overwrites"] is False and p["windowsfilenames"] is True
    assert p["quiet"] and p["no_warnings"] and p["noprogress"]
    assert p["socket_timeout"] == 30
    assert p["paths"] == {"home": "/t", "temp": "/t"}
    assert p["outtmpl"] == "%(id)s.%(ext)s"
    assert p["ffmpeg_location"] == "/f/ffmpeg"
    assert p["js_runtimes"] == {"deno": {"path": "/opt/bin/deno"}}
    for forbidden in ("cookiefile", "cookiesfrombrowser", "username", "allow_unplayable_formats"):
        assert forbidden not in p
    assert set(p["retry_sleep_functions"]) >= {"http", "fragment", "extractor"}


def test_base_params_minimal() -> None:
    p = base_params()
    for key in ("paths", "ffmpeg_location", "js_runtimes", "logger", "progress_hooks"):
        assert key not in p


def test_backoff_growth_and_cap() -> None:
    assert [backoff(n) for n in range(6)] == [1, 2, 4, 8, 16, 30]
    assert backoff(100) == 30 and backoff(-1) == 1
    p = base_params()
    assert p["retry_sleep_functions"]["http"](2) == 4


def test_params_are_accepted_by_real_yt_dlp() -> None:
    """Option names must exist: yt-dlp warns about unknown JS runtimes, and stores the rest."""
    yt_dlp = pytest.importorskip("yt_dlp")
    warnings: list[str] = []

    class Log:
        def debug(self, m: str) -> None: ...
        def info(self, m: str) -> None: ...
        def warning(self, m: str) -> None:
            warnings.append(m)

        def error(self, m: str) -> None:
            warnings.append(m)

    params = base_params(js_runtime=JsRuntime("deno", Path("/x/deno")), logger=Log())
    params["no_warnings"] = False
    with yt_dlp.YoutubeDL(params) as ydl:
        assert ydl.params["js_runtimes"] == {"deno": {"path": "/x/deno"}}
        assert ydl.params["retries"] == 3 and ydl.params["noplaylist"] is True
    assert warnings == []
    for name in ("deno", "node", "quickjs", "bun"):
        with yt_dlp.YoutubeDL(base_params(js_runtime=JsRuntime(name, Path("/x/rt")))) as ydl:
            assert name in ydl.params["js_runtimes"]


def test_logger_routes_to_sink() -> None:
    seen: list[str] = []

    class Sink:
        def debug(self, message: str) -> None:
            seen.append(message)

    lg = StderrLogger(Sink())
    lg.debug("a")
    lg.info("b")
    lg.warning("c")
    lg.error("d")
    assert seen == ["a", "b", "yt-dlp warning: c", "yt-dlp error: d"]


def test_progress_from_hook() -> None:
    p = progress_from_hook(
        {"status": "downloading", "downloaded_bytes": 10, "total_bytes_estimate": 100.0,
         "speed": 5, "eta": 3}
    )  # fmt: skip
    assert (p.downloaded_bytes, p.total_bytes, p.speed, p.eta, p.status) == (
        10, 100, 5.0, 3, "downloading",
    )  # fmt: skip
    q = progress_from_hook({"status": "finished", "downloaded_bytes": True})
    assert q.status == "finished" and q.downloaded_bytes == 0 and q.total_bytes is None


def test_find_downloaded(tmp_path: Path) -> None:
    f = tmp_path / "abc.m4a"
    f.write_text("x")
    assert find_downloaded({"requested_downloads": [{"filepath": str(f)}]}, tmp_path) == f
    assert find_downloaded({"filepath": str(f)}, tmp_path) == f
    (tmp_path / "abc.m4a.part").write_text("p")
    assert find_downloaded({"id": "abc"}, tmp_path) == f
    assert find_downloaded({"id": "zzz"}, tmp_path) is None
    assert find_downloaded({}, tmp_path) == f


# ------------------------------------------------------------ probe (T4.1)
def test_probe_maps_info(tmp_path: Path) -> None:
    FakeDL.instances.clear()
    media = Extractor(ffmpeg_location=Path("/f"), js_runtime=JS).probe(REF)
    assert media.id == "dQw4w9WgXcQ" and media.formats[0].format_id == "140"
    dl = FakeDL.instances[0]
    assert dl.calls == [(REF.canonical_url, False)]
    assert dl.params["js_runtimes"] == {"deno": {"path": "/opt/bin/deno"}}


def test_probe_playlist_result_uses_first_entry() -> None:
    ex = Extractor()
    ex.result = {"_type": "playlist", "entries": [None, INFO]}
    assert ex.probe(REF).title == "T"
    ex.result = {"_type": "playlist", "entries": []}
    with pytest.raises(InternalError):
        ex.probe(REF)
    ex.result = None
    with pytest.raises(InternalError):
        ex.probe(REF)


class FakeDownloadError(Exception):
    """Named like yt-dlp's so the pure classifier recognises it by class name."""


FakeDownloadError.__name__ = "DownloadError"


def dl_error(msg: str, inner: BaseException | None = None) -> Exception:
    exc = FakeDownloadError(msg)
    if inner is not None:
        exc.exc_info = (type(inner), inner, None)  # type: ignore[attr-defined]
    return exc


@pytest.mark.parametrize(
    ("exc", "cls", "code"),
    [
        (dl_error("ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in"), VideoUnavailable, 3),
        (dl_error("ERROR: [youtube] x: Video unavailable"), VideoUnavailable, 3),
        (
            dl_error(
                "ERROR: [youtube] x: The uploader has not made this video available in your country"
            ),
            VideoUnavailable,
            3,
        ),
        (dl_error("ERROR: [youtube] x: Sign in to confirm your age"), VideoUnavailable, 3),
        (dl_error("ERROR: [youtube] x: Sign in to confirm you're not a bot"), VideoUnavailable, 3),
        (dl_error("ERROR: unable to download video data: HTTP Error 503"), NetworkError, 4),
        (dl_error("ERROR: Unable to download webpage: timed out"), NetworkError, 4),
        (dl_error("x", ConnectionResetError("reset")), NetworkError, 4),
        (dl_error("ERROR: Unable to extract uploader id"), InternalError, 1),
        (
            dl_error("ERROR: unable to write data: [Errno 28] No space left on device"),
            FileSystemError,
            7,
        ),
        (dl_error("x", OSError(errno.EACCES, "Permission denied", "/o")), FileSystemError, 7),
        (OSError(errno.ENOSPC, "No space left on device"), FileSystemError, 7),
        (dl_error("ERROR: ffmpeg not found. Please install"), MissingDependency, 5),
        (RuntimeError("weird"), InternalError, 1),
    ],
)
def test_error_translation(exc: Exception, cls: type[XtractorError], code: int) -> None:
    ex = Extractor()
    ex.exc = exc
    for call in (
        lambda: ex.probe(REF),
        lambda: ex.download(REF, "140", Path("/t"), "o", None, print),
    ):
        with pytest.raises(cls) as info:
            call()
        assert info.value.exit_code == code
    ex.exc = None


def test_extraction_failure_has_update_hint() -> None:
    ex = Extractor()
    ex.exc = dl_error("ERROR: Unable to extract initial player response")
    with pytest.raises(InternalError) as info:
        ex.probe(REF)
    assert "Xtractor" in str(info.value) or "updating" in str(info.value)
    assert "dQw4w9WgXcQ" in str(info.value)


def test_xtractor_errors_pass_through_and_ctrl_c_is_not_swallowed() -> None:
    ex = Extractor()
    ex.exc = VideoUnavailable("x")  # type: ignore[assignment]
    with pytest.raises(VideoUnavailable):
        ex.probe(REF)
    ex.exc = KeyboardInterrupt()  # type: ignore[assignment]
    with pytest.raises(KeyboardInterrupt):
        ex.download(REF, "140", Path("/t"), "o", None, print)


# ------------------------------------------------------------ download (T4.2)
def test_download_params_and_progress(tmp_path: Path) -> None:
    f = tmp_path / "dQw4w9WgXcQ.mp4"
    f.write_text("x")
    ex = Extractor(js_runtime=JS)
    ex.result = {"id": "dQw4w9WgXcQ", "requested_downloads": [{"filepath": str(f)}]}
    FakeDL.instances.clear()
    events = []
    got = ex.download(REF, "137+140", tmp_path, "%(id)s.%(ext)s", "mp4", events.append)
    assert got == f
    dl = FakeDL.instances[0]
    assert dl.calls == [(REF.canonical_url, True)]
    p = dl.params
    assert p["format"] == "137+140" and p["merge_output_format"] == "mp4"
    assert p["postprocessors"] == [{"key": "FFmpegMetadata", "add_metadata": True}]
    assert p["paths"]["home"] == str(tmp_path) and p["continuedl"] and p["retries"] == 3
    p["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
    assert events[0].downloaded_bytes == 5 and events[0].total_bytes == 10


def test_audio_download_has_no_merge_or_postprocessors(tmp_path: Path) -> None:
    f = tmp_path / "dQw4w9WgXcQ.m4a"
    f.write_text("x")
    ex = Extractor()
    ex.result = {"id": "dQw4w9WgXcQ", "requested_downloads": [{"filepath": str(f)}]}
    FakeDL.instances.clear()
    ex.download(REF, AAC_441.format_id, tmp_path, "%(id)s.%(ext)s", None, print)
    p = FakeDL.instances[0].params
    assert "merge_output_format" not in p and "postprocessors" not in p


def test_download_without_result_file_is_internal_error(tmp_path: Path) -> None:
    ex = Extractor()
    ex.result = {"id": "dQw4w9WgXcQ"}
    with pytest.raises(InternalError, match="no file"):
        ex.download(REF, "140", tmp_path, "o", None, print)
    ex.result = "garbage"
    with pytest.raises(InternalError):
        ex.download(REF, "140", tmp_path, "o", None, print)


def test_real_youtube_dl_factory_is_lazy_import() -> None:
    ydl = YtDlpExtractor()._youtube_dl(base_params())
    assert type(ydl).__name__ == "YoutubeDL"
    ydl.close()
