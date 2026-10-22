"""yt-dlp adapter: the ONLY module allowed to import ``yt_dlp``.

Interface only for now; the implementation (probe, download, error translation via
``errors.classify_exception``) lands in milestone M4.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import InternalError
from .formats import MediaInfo
from .urls import VideoRef


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


class YtDlpExtractor:
    """Real extractor backed by ``yt_dlp.YoutubeDL`` (not implemented yet)."""

    def probe(self, ref: VideoRef) -> MediaInfo:
        raise InternalError("YtDlpExtractor.probe is not implemented yet")

    def download(
        self,
        ref: VideoRef,
        format_selector: str,
        dest_dir: Path,
        outtmpl: str,
        merge_to: str | None,
        on_progress: Callable[[Progress], None],
    ) -> Path:
        raise InternalError("YtDlpExtractor.download is not implemented yet")
