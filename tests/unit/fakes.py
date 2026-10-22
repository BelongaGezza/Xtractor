"""Test doubles shared by pipeline and CLI tests."""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from pathlib import Path

from xtractor.formats import FormatInfo, MediaInfo
from xtractor.pipeline import Deps
from xtractor.ui import Reporter
from xtractor.urls import VideoRef
from xtractor.ytdlp import Progress

from .fixtures import AAC_441, AVC, OPUS, standard_formats


def info_with(formats: Sequence[FormatInfo], **kw: object) -> MediaInfo:
    base: dict[str, object] = {
        "id": "dQw4w9WgXcQ",
        "title": "My: Title/?",
        "uploader": "Chan",
        "upload_date": "20240131",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }
    base.update(kw)
    return MediaInfo(formats=tuple(formats), **base)  # type: ignore[arg-type]


class FakeExtractor:
    """Serves a canned ``MediaInfo``; "downloads" by writing a small stub file."""

    def __init__(
        self,
        info: MediaInfo | None = None,
        *,
        fail_probe: BaseException | None = None,
        on_download: Callable[[Path], None] | None = None,
        content: bytes = b"stub-media",
    ) -> None:
        self.info = info or info_with(standard_formats())
        self.fail_probe = fail_probe
        self.on_download = on_download
        self.content = content
        self.probes: list[VideoRef] = []
        self.downloads: list[tuple[str, Path, str, str | None]] = []

    def probe(self, ref: VideoRef) -> MediaInfo:
        self.probes.append(ref)
        if self.fail_probe is not None:
            raise self.fail_probe
        return self.info

    def download(
        self,
        ref: VideoRef,
        format_selector: str,
        dest_dir: Path,
        outtmpl: str,
        merge_to: str | None,
        on_progress: Callable[[Progress], None],
    ) -> Path:
        self.downloads.append((format_selector, dest_dir, outtmpl, merge_to))
        on_progress(Progress(50, 100, 10.0, 5, "downloading"))
        ext = merge_to or ("m4a" if format_selector == AAC_441.format_id else "webm")
        path = dest_dir / f"{ref.video_id}.{ext}"
        path.write_bytes(self.content)
        part = dest_dir / f"{ref.video_id}.f140.m4a.part"
        part.write_bytes(b"partial")
        if self.on_download is not None:
            self.on_download(dest_dir)
        on_progress(Progress(100, 100, 10.0, 0, "finished"))
        part.unlink()
        return path


class FakeFfmpeg:
    """Records argv and writes the output file (last argument)."""

    def __init__(self, fail: BaseException | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv: Sequence[str]) -> None:
        self.calls.append(list(argv))
        if self.fail is not None:
            raise self.fail
        Path(argv[-1]).write_bytes(b"converted")


def make_deps(
    extractor: FakeExtractor | None = None,
    ffmpeg: FakeFfmpeg | None = None,
    *,
    quiet: bool = False,
    cwd: Path | None = None,
) -> tuple[Deps, io.StringIO]:
    err = io.StringIO()
    deps = Deps(
        extractor=extractor or FakeExtractor(),
        reporter=Reporter(quiet=quiet, stream=err),
        run_ffmpeg=ffmpeg or FakeFfmpeg(),
        ffmpeg_bin="ffmpeg",
        cwd=cwd,
    )
    return deps, err


__all__ = ["AAC_441", "AVC", "OPUS", "FakeExtractor", "FakeFfmpeg", "info_with", "make_deps"]
