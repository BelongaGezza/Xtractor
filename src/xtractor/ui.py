"""User-facing output on stderr: messages, verbosity and download progress rendering."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO

from .ytdlp import Progress

PROG = "Xtractor"
NON_TTY_PERCENT_STEP = 10
NON_TTY_SECONDS = 5.0


def human_size(n: float | None) -> str:
    if n is None:
        return "?"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"  # pragma: no cover


def human_eta(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_progress(p: Progress) -> str:
    """One status line: percent, size, speed, ETA."""
    if p.total_bytes:
        pct = f"{min(100.0, 100.0 * p.downloaded_bytes / p.total_bytes):5.1f}%"
        size = human_size(p.total_bytes)
    else:
        pct = "  ?  "
        size = human_size(p.downloaded_bytes)
    speed = f"{human_size(p.speed)}/s" if p.speed else "?/s"
    return f"{pct} of {size} at {speed} ETA {human_eta(p.eta)}"


class Reporter:
    """Writes everything to ``stream`` (stderr); never to stdout."""

    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        stream: TextIO | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.stream: TextIO = stream if stream is not None else sys.stderr
        self._clock = clock
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._line_open = False
        self._last_pct = -NON_TTY_PERCENT_STEP
        self._last_time: float | None = None
        self._last_bytes = 0

    # -- messages ---------------------------------------------------------
    def _write(self, text: str) -> None:
        self._close_line()
        print(text, file=self.stream)

    def info(self, message: str) -> None:
        if not self.quiet:
            self._write(message)

    def notice(self, message: str) -> None:
        if not self.quiet:
            self._write(f"{PROG}: note: {message}")

    def warn(self, message: str) -> None:
        if not self.quiet:
            self._write(f"{PROG}: warning: {message}")

    def error(self, message: str) -> None:
        self._write(f"{PROG}: error: {message}")

    def debug(self, message: str) -> None:
        if self.verbose and not self.quiet:
            self._write(message)

    # -- progress -----------------------------------------------------------
    def progress(self, p: Progress) -> None:
        if self.quiet:
            return
        if self._tty:
            line = render_progress(p)
            print(f"\r\x1b[2K{line}", end="", file=self.stream, flush=True)
            self._line_open = True
            if p.status == "finished":
                self._close_line()
            return
        if p.downloaded_bytes < self._last_bytes:  # a new stream started (video, then audio)
            self._last_pct = -NON_TTY_PERCENT_STEP
            self._last_time = None
        self._last_bytes = p.downloaded_bytes
        now = self._clock()
        pct = int(100 * p.downloaded_bytes / p.total_bytes) if p.total_bytes else None
        already_complete = pct is not None and pct >= 100 and self._last_pct >= 100
        if p.status == "finished" and already_complete:
            return
        due = (
            p.status == "finished"
            or self._last_time is None
            or now - self._last_time >= NON_TTY_SECONDS
            or (pct is not None and pct >= self._last_pct + NON_TTY_PERCENT_STEP)
        )
        if due:
            self._last_time = now
            if pct is not None:
                self._last_pct = pct
            print(render_progress(p), file=self.stream, flush=True)

    def reset_progress(self) -> None:
        """Forget per-file progress state (call before each new download)."""
        self._close_line()
        self._last_pct = -NON_TTY_PERCENT_STEP
        self._last_time = None
        self._last_bytes = 0

    def _close_line(self) -> None:
        if self._line_open:
            print(file=self.stream)
            self._line_open = False
