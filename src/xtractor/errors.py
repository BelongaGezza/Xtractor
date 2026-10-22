"""Exception hierarchy, exit codes and the pure exception classifier.

Nothing here imports yt-dlp: third-party exceptions are recognised by class name
(walking the MRO) and message text so this module stays importable and testable
without any I/O dependency.
"""

from __future__ import annotations

import errno
import re
import sys

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3
EXIT_NETWORK = 4
EXIT_MISSING_DEP = 5
EXIT_FORMAT = 6
EXIT_FILESYSTEM = 7
EXIT_INTERRUPTED = 130

EXIT_CODE_TABLE: tuple[tuple[int, str], ...] = (
    (EXIT_OK, "Success (or skipped because the file already exists)"),
    (EXIT_INTERNAL, "Unexpected or internal error"),
    (EXIT_USAGE, "Usage error / invalid arguments"),
    (EXIT_UNAVAILABLE, "Video unavailable (private, removed, blocked, DRM, live)"),
    (EXIT_NETWORK, "Network error after retries"),
    (EXIT_MISSING_DEP, "Missing dependency (ffmpeg or JavaScript runtime)"),
    (EXIT_FORMAT, "Requested format/resolution cannot be satisfied (--strict-format)"),
    (EXIT_FILESYSTEM, "File system error (permissions, disk full)"),
    (EXIT_INTERRUPTED, "Interrupted (Ctrl-C / SIGTERM)"),
)

UPDATE_HINT = "try updating yt-dlp: pipx upgrade Xtractor"


class XtractorError(Exception):
    """Base class; every subclass carries the process exit code."""

    exit_code: int = EXIT_INTERNAL

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} ({self.hint})" if self.hint else self.message


class InternalError(XtractorError):
    exit_code = EXIT_INTERNAL


class UsageError(XtractorError):
    exit_code = EXIT_USAGE


class VideoUnavailable(XtractorError):
    exit_code = EXIT_UNAVAILABLE


class NetworkError(XtractorError):
    exit_code = EXIT_NETWORK


class MissingDependency(XtractorError):
    exit_code = EXIT_MISSING_DEP


class FormatUnavailable(XtractorError):
    exit_code = EXIT_FORMAT


class FileSystemError(XtractorError):
    exit_code = EXIT_FILESYSTEM


class Interrupted(XtractorError):
    exit_code = EXIT_INTERRUPTED


_FS_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.EPERM,
        errno.ENOSPC,
        errno.EROFS,
        errno.EDQUOT,
        errno.ENAMETOOLONG,
    }
)

_UNAVAILABLE_PATTERNS = (
    "private video",
    "video unavailable",
    "this video is unavailable",
    "not available in your country",
    "not made this video available",
    "blocked it in your country",
    "has been removed",
    "removed by the uploader",
    "account associated with this video has been terminated",
    "sign in to confirm your age",
    "age-restricted",
    "confirm your age",
    "sign in to confirm you",  # "...you're not a bot"
    "members-only",
    "members only",
    "join this channel",
    "copyright",
    "drm",
    "premieres in",
    "this live event will begin",
    "live stream recording is not available",
    "is live",
)

_NETWORK_PATTERNS = (
    "http error 429",
    "http error 5",
    "unable to download",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "connection aborted",
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname",
    "network is unreachable",
    "ssl",
    "incomplete read",
    "transporterror",
)

_JS_RUNTIME_RE = re.compile(r"(javascript|js) runtime|\bdeno\b|\bnode\.?js\b", re.IGNORECASE)
_FFMPEG_RE = re.compile(r"ffmpeg|ffprobe|avconv", re.IGNORECASE)
_NETWORK_TYPES = frozenset(
    {
        "TransportError",
        "URLError",
        "ContentTooShortError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "IncompleteRead",
        "timeout",
    }
)


def _type_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def ffmpeg_install_hint(platform: str | None = None) -> str:
    """Return a platform-specific ffmpeg installation hint."""
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        return "install it with: brew install ffmpeg"
    if plat.startswith("win"):
        return "install it with: winget install ffmpeg"
    return "install it with your package manager, e.g. sudo apt install ffmpeg"


def _innermost(exc: BaseException) -> BaseException:
    """yt-dlp's DownloadError wraps the real error in ``exc_info``."""
    info = getattr(exc, "exc_info", None)
    if isinstance(info, tuple) and len(info) > 1 and isinstance(info[1], BaseException):
        return info[1]
    return exc


def classify_exception(exc: BaseException, *, video_id: str | None = None) -> XtractorError:
    """Map any exception to an :class:`XtractorError` carrying the right exit code.

    Pure function over the exception type names and message text.
    """
    if isinstance(exc, XtractorError):
        return exc
    if isinstance(exc, KeyboardInterrupt):
        return Interrupted("interrupted")

    inner = _innermost(exc)
    names = _type_names(exc) | _type_names(inner)
    text = str(exc)
    low = text.lower()
    suffix = f" [{video_id}]" if video_id else ""

    # Dependencies first: they are actionable and unambiguous.
    if isinstance(exc, FileNotFoundError) and _FFMPEG_RE.search(str(exc.filename or "")):
        return MissingDependency("ffmpeg was not found", hint=ffmpeg_install_hint())
    if "unknown encoder" in low or ("encoder" in low and "not found" in low):
        return MissingDependency(
            f"your ffmpeg build lacks a required encoder: {text.strip()}",
            hint="install a full ffmpeg build",
        )
    if _JS_RUNTIME_RE.search(text) and ("no " in low or "missing" in low or "not " in low):
        return MissingDependency(
            "a JavaScript runtime is required to read this video", hint="install deno or node"
        )
    if "ffmpeg" in low and (
        "not found" in low or "not installed" in low or "is not available" in low
    ):
        return MissingDependency("ffmpeg was not found", hint=ffmpeg_install_hint())

    is_yt_error = bool(names & {"DownloadError", "ExtractorError", "GeoRestrictedError"})
    if is_yt_error or "UnavailableVideoError" in names:
        if "GeoRestrictedError" in names or any(p in low for p in _UNAVAILABLE_PATTERNS):
            reason = _clean_ytdlp_message(text)
            return VideoUnavailable(f"video unavailable{suffix}: {reason}")
        if names & _NETWORK_TYPES or any(p in low for p in _NETWORK_PATTERNS):
            return NetworkError(f"network error{suffix}: {_clean_ytdlp_message(text)}")
        return InternalError(
            f"extraction failed{suffix}: {_clean_ytdlp_message(text)}", hint=UPDATE_HINT
        )

    if names & _NETWORK_TYPES or isinstance(inner, TimeoutError):
        return NetworkError(f"network error{suffix}: {text}")

    if isinstance(exc, OSError) and exc.errno in _FS_ERRNOS:
        where = f" ({exc.filename})" if exc.filename else ""
        return FileSystemError(f"{exc.strerror or text}{where}")

    return InternalError(f"unexpected error: {type(exc).__name__}: {text}")


def _clean_ytdlp_message(text: str) -> str:
    """Strip the ``ERROR:`` prefix, ``[youtube] id:`` tag and ANSI codes."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    text = re.sub(r"^\[[\w:+-]+\]\s*(?:[\w-]+:\s+)?", "", text)
    return text.splitlines()[0].strip() if text else "unknown reason"
