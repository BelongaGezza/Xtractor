"""YouTube URL validation and canonicalisation. Pure: no network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .errors import UsageError

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_SHORT_HOST = "youtu.be"
_ID_PATH_PREFIXES = ("shorts", "live")
_CHANNEL_PREFIXES = ("channel", "c", "user")


@dataclass(frozen=True)
class VideoRef:
    video_id: str
    canonical_url: str
    #: True when the input carried a ``list=`` parameter (ignored; informational).
    had_playlist_param: bool = False


def _canonical(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _check_id(candidate: str | None, original: str) -> str:
    if not candidate or not _VIDEO_ID_RE.match(candidate):
        raise UsageError(
            f"not a valid YouTube video ID: {candidate!r} in {original!r} "
            "(expected 11 characters: letters, digits, '-' or '_')"
        )
    return candidate


def parse_youtube_url(raw: str) -> VideoRef:
    """Parse ``raw`` into a :class:`VideoRef` or raise :class:`UsageError`.

    Accepted: ``youtube.com/watch?v=``, ``youtu.be/``, ``/shorts/``, ``/live/`` on
    ``youtube.com``, ``m.youtube.com`` and ``music.youtube.com``. A ``list=``
    parameter next to a video is ignored (single video only); bare playlists and
    channels are rejected. Tracking parameters are dropped from the canonical URL.
    """
    text = (raw or "").strip()
    if not text:
        raise UsageError("URL is empty")
    if any(ch.isspace() or ord(ch) < 32 for ch in text):
        raise UsageError(f"malformed URL (contains whitespace or control characters): {raw!r}")
    if "://" not in text and re.match(r"^[\w.-]+/", text):
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise UsageError(f"malformed URL: {raw!r} ({exc})") from exc
    if parts.scheme not in ("http", "https"):
        raise UsageError(f"unsupported URL scheme in {raw!r}: only http and https are accepted")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UsageError(f"malformed URL (no host): {raw!r}")
    if port is not None or parts.username or parts.password:
        raise UsageError(f"unsupported URL (port or credentials present): {raw!r}")

    query = parse_qs(parts.query)
    has_list = bool(query.get("list"))
    segments = [s for s in parts.path.split("/") if s]

    if host == _SHORT_HOST:
        if len(segments) != 1:
            raise UsageError(f"not a YouTube video URL: {raw!r}")
        return VideoRef(_check_id(segments[0], raw), _canonical(segments[0]), has_list)

    if host not in _YOUTUBE_HOSTS:
        raise UsageError(
            f"not a YouTube URL: {raw!r} (host {host!r}; Xtractor v1 supports YouTube only)"
        )

    first = segments[0] if segments else ""
    if first == "watch" and len(segments) == 1:
        v = query.get("v", [""])[0]
        if not v:
            if has_list:
                raise UsageError("playlists are not supported in v1: give a single video URL")
            raise UsageError(f"YouTube URL has no video ID (missing v=): {raw!r}")
        return VideoRef(_check_id(v, raw), _canonical(v), has_list)
    if first in _ID_PATH_PREFIXES and len(segments) == 2:
        return VideoRef(_check_id(segments[1], raw), _canonical(segments[1]), has_list)
    if first == "playlist":
        raise UsageError("playlists are not supported in v1: give a single video URL")
    if first in _CHANNEL_PREFIXES or first.startswith("@"):
        raise UsageError("channels are not supported in v1: give a single video URL")
    raise UsageError(f"not a recognised YouTube video URL: {raw!r}")
