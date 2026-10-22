"""Pure format models and selection logic (no I/O).

``FormatInfo``/``MediaInfo`` are the only shapes the rest of Xtractor sees of a
yt-dlp info dict; ``from_dict`` is the single mapping point.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .errors import FormatUnavailable, VideoUnavailable
from .options import DEFAULT_BITRATE, AudioOptions, VideoOptions

DEFAULT_LOSSY_BITRATE = DEFAULT_BITRATE
_NOMINAL_RE = re.compile(r"^(\d{3,4})p")
AUDIO_EXT = {"m4a": "m4a", "mp3": "mp3", "opus": "opus", "flac": "flac", "wav": "wav"}


@dataclass(frozen=True)
class FormatInfo:
    format_id: str
    ext: str = ""
    vcodec: str = "none"
    acodec: str = "none"
    height: int | None = None
    fps: float | None = None
    asr: int | None = None
    abr: float | None = None
    tbr: float | None = None
    has_drm: bool = False
    filesize: int | None = None
    note: str = ""
    label: str = ""  # yt-dlp's descriptive ``format`` string
    language: str | None = None
    language_preference: float | None = None
    protocol: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FormatInfo:
        def num(key: str) -> float | None:
            v = d.get(key)
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

        def integer(key: str) -> int | None:
            v = num(key)
            return int(v) if v is not None else None

        # Letterboxed videos report e.g. height=818 for the "1080p" rung. Users think in
        # the nominal rung, so prefer the number in format_note ("1080p", "720p60").
        note = str(d.get("format_note") or "")
        nominal = _NOMINAL_RE.match(note)
        height = int(nominal.group(1)) if nominal else integer("height")

        size = integer("filesize") or integer("filesize_approx")
        return cls(
            format_id=str(d.get("format_id", "")),
            ext=str(d.get("ext") or ""),
            vcodec=str(d.get("vcodec") or "none"),
            acodec=str(d.get("acodec") or "none"),
            height=height,
            fps=num("fps"),
            asr=integer("asr"),
            abr=num("abr"),
            tbr=num("tbr"),
            has_drm=bool(d.get("has_drm")),
            filesize=size,
            note=note,
            label=str(d.get("format") or ""),
            language=str(d["language"]) if d.get("language") else None,
            language_preference=num("language_preference"),
            protocol=str(d.get("protocol") or ""),
        )

    # -- classification ---------------------------------------------------
    @property
    def is_drc(self) -> bool:
        """Dynamic-range-compressed variant (YouTube ``140-drc``): never preferred."""
        return (
            self.format_id.lower().endswith("-drc")
            or "drc" in self.note.lower()
            or "drc" in self.label.lower()
        )

    @property
    def original_rank(self) -> tuple[float, int]:
        """Ranks the original-language track above dubs (YouTube multi-audio videos).

        yt-dlp gives the original track ``language_preference`` 10 and dubs -1; the note
        also says "original" / "(default)". Formats without language data rank 0.
        """
        note = self.note.lower()
        marked = 1 if "original" in note or "(default)" in note else 0
        return (self.language_preference or 0.0, marked)

    @property
    def is_hls(self) -> bool:
        return "m3u8" in self.protocol

    @property
    def has_video(self) -> bool:
        return self.vcodec not in ("none", "")

    @property
    def has_audio(self) -> bool:
        return self.acodec not in ("none", "")

    @property
    def audio_only(self) -> bool:
        return self.has_audio and not self.has_video

    @property
    def video_only(self) -> bool:
        return self.has_video and not self.has_audio

    @property
    def is_aac(self) -> bool:
        return self.acodec.lower().startswith("mp4a")

    @property
    def is_opus(self) -> bool:
        return self.acodec.lower().startswith("opus")

    @property
    def vfamily(self) -> str:
        v = self.vcodec.lower()
        if v.startswith(("avc1", "h264")):
            return "avc1"
        if v.startswith(("vp9", "vp09")):
            return "vp9"
        if v.startswith(("av01", "av1")):
            return "av1"
        return "other"

    @property
    def quality(self) -> float:
        return self.abr or self.tbr or 0.0


@dataclass(frozen=True)
class MediaInfo:
    id: str
    title: str
    uploader: str | None = None
    upload_date: str | None = None  # YYYYMMDD
    webpage_url: str | None = None
    live_status: str | None = None
    is_live: bool = False
    formats: tuple[FormatInfo, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> MediaInfo:
        return cls(
            id=str(d.get("id", "")),
            title=str(d.get("title") or ""),
            uploader=d.get("uploader") or d.get("channel"),
            upload_date=d.get("upload_date"),
            webpage_url=d.get("webpage_url"),
            live_status=d.get("live_status"),
            is_live=bool(d.get("is_live")),
            formats=tuple(FormatInfo.from_dict(f) for f in d.get("formats") or []),
        )


@dataclass(frozen=True)
class Tags:
    title: str | None = None
    artist: str | None = None
    date: str | None = None
    url: str | None = None

    @classmethod
    def from_media(cls, info: MediaInfo, url: str | None = None) -> Tags:
        d = info.upload_date
        date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 and d.isdigit() else None
        return cls(info.title or None, info.uploader, date, url or info.webpage_url)


def check_playable(info: MediaInfo) -> None:
    """Reject live/upcoming streams and DRM-only media (exit 3)."""
    status = info.live_status or ""
    if info.is_live or status in ("is_live", "is_upcoming", "post_live"):
        raise VideoUnavailable(
            f"video unavailable [{info.id}]: live streams, premieres and unfinished "
            "live recordings cannot be downloaded"
        )
    usable = [f for f in info.formats if not f.has_drm]
    if info.formats and not usable:
        raise VideoUnavailable(f"video unavailable [{info.id}]: all streams are DRM-protected")
    if not info.formats:
        raise VideoUnavailable(f"video unavailable [{info.id}]: no downloadable formats found")


# ---------------------------------------------------------------- audio
@dataclass(frozen=True)
class AudioPlan:
    format_id: str
    copy: bool
    ext: str
    ffmpeg_codec_args: tuple[str, ...]
    notices: tuple[str, ...] = ()


def preferred_audio(cands: Sequence[FormatInfo]) -> list[FormatInfo]:
    """Keep the original-language track and prefer plain streams over DRC variants.

    Multi-audio (auto-dubbed) videos offer one stream per language at equal bitrate; picking
    by bitrate alone returns a random dub. DRC variants are louder/compressed re-encodes of
    the same track: only a last resort.
    """
    if not cands:
        return []
    top = max(f.original_rank for f in cands)
    originals = [f for f in cands if f.original_rank == top]
    return [f for f in originals if not f.is_drc] or originals


def _audio_candidates(formats: Sequence[FormatInfo]) -> list[FormatInfo]:
    cands = [f for f in formats if f.audio_only and not f.has_drm]
    if not cands:
        raise VideoUnavailable("no downloadable audio streams found")
    return preferred_audio(cands)


def _best(cands: Sequence[FormatInfo]) -> FormatInfo:
    # Highest bitrate; opus wins ties (better quality per bit); stable by format id.
    return max(cands, key=lambda f: (f.quality, f.is_opus, f.asr or 0))


def select_audio(formats: Sequence[FormatInfo], opts: AudioOptions) -> AudioPlan:
    """Choose the source stream and ffmpeg codec arguments for the requested audio output."""
    cands = _audio_candidates(formats)
    rate, br, fmt = opts.sample_rate, opts.bitrate, opts.fmt
    lossy_br = br or DEFAULT_LOSSY_BITRATE
    notices: list[str] = []

    if fmt == "m4a":
        aac = [f for f in cands if f.is_aac]
        exact = [f for f in aac if f.asr == rate]
        if exact and br is None:
            src = _best(exact)
            return AudioPlan(
                src.format_id, True, "m4a", ("-c:a", "copy", "-movflags", "+faststart")
            )
        src = _best(exact or aac or cands)
        if src.asr and src.asr != rate:
            notices.append(
                f"source audio is {src.asr} Hz; transcoding to AAC at {rate} Hz "
                "(copy is only possible when the rates match)"
            )
        elif not src.is_aac:
            notices.append("no AAC stream available; transcoding to AAC")
        return AudioPlan(
            src.format_id,
            False,
            "m4a",
            ("-c:a", "aac", "-b:a", lossy_br, "-ar", str(rate)),
            tuple(notices),
        )

    if fmt == "opus":
        opus = [f for f in cands if f.is_opus]
        src = _best(opus or cands)
        if src.is_opus and src.asr == 48000 and br is None and rate == 48000:
            return AudioPlan(src.format_id, True, "opus", ("-c:a", "copy"))
        if not src.is_opus:
            notices.append("no Opus stream available; transcoding to Opus")
        return AudioPlan(
            src.format_id,
            False,
            "opus",
            ("-c:a", "libopus", "-b:a", lossy_br, "-ar", "48000"),
            tuple(notices),
        )

    src = _best(cands)
    args: tuple[str, ...]
    if src.asr and src.asr != rate:
        notices.append(f"resampling {src.asr} Hz -> {rate} Hz")
    if fmt == "mp3":
        args = ("-c:a", "libmp3lame", "-b:a", lossy_br, "-ar", str(rate))
    elif fmt == "flac":
        notices.append("flac is lossless but the YouTube source is lossy: no fidelity is gained")
        args = ("-c:a", "flac", "-ar", str(rate))
    else:  # wav
        args = ("-c:a", "pcm_s16le", "-ar", str(rate))
    return AudioPlan(src.format_id, False, AUDIO_EXT[fmt], args, tuple(notices))


# ---------------------------------------------------------------- video
@dataclass(frozen=True)
class VideoPlan:
    format_selector: str  # e.g. "137+140", or a single id for a muxed fallback
    container: str  # mp4 | mkv | webm
    video_format_id: str
    audio_format_id: str | None
    height: int | None
    notices: tuple[str, ...] = ()


_CODEC_PREF = {"vp9": 3, "av1": 2, "avc1": 1, "other": 0}


def _vkey(f: FormatInfo, *, prefer_avc: bool = False) -> tuple[float, ...]:
    pref = (1.0 if f.vfamily == "avc1" else 0.0) if prefer_avc else float(_CODEC_PREF[f.vfamily])
    # Ties on height/fps/codec: prefer progressive DASH over HLS (m3u8) variants, then bitrate.
    return (f.height or 0, f.fps or 0.0, pref, 0.0 if f.is_hls else 1.0, f.tbr or 0.0)


def _plan(v: FormatInfo, a: FormatInfo, container: str, notices: list[str]) -> VideoPlan:
    return VideoPlan(
        f"{v.format_id}+{a.format_id}",
        container,
        v.format_id,
        a.format_id,
        v.height,
        tuple(notices),
    )


def select_video(formats: Sequence[FormatInfo], opts: VideoOptions) -> VideoPlan:
    """Choose video and audio streams plus the output container (spec 3.3, plan 2.4)."""
    usable = [f for f in formats if not f.has_drm]
    vids = [f for f in usable if f.video_only and f.height]
    auds = preferred_audio([f for f in usable if f.audio_only])
    if not vids or not auds:
        return _muxed_fallback(usable, opts)

    limit = opts.max_height
    cap = limit if limit is not None else 10**6
    fmt = opts.fmt
    notices: list[str] = []

    below = [f for f in vids if (f.height or 0) <= cap]
    if not below:
        if opts.strict:
            raise FormatUnavailable(f"no video stream at or below {limit}p is available")
        lowest = min(vids, key=lambda f: f.height or 0)
        notices.append(f"{limit}p unavailable, using lowest available ({lowest.height}p)")
        below = [f for f in vids if f.height == lowest.height]
    overall_best_h = max(f.height or 0 for f in below)

    best_audio = _best(auds)
    aac = [f for f in auds if f.is_aac and f.ext == "m4a"]
    opus = [f for f in auds if f.is_opus]

    def switch_notice(target: str, why: str) -> str:
        return f"container switched {fmt} -> {target} ({why})"

    if fmt == "mp4":
        avc = [f for f in below if f.vfamily == "avc1" and (f.height or 0) <= 1080]
        if overall_best_h <= 1080 and avc and aac:
            v = max(avc, key=_vkey)
            _note_height(notices, limit, v.height, "mp4/H.264")
            return _plan(v, _best(aac), "mp4", notices)
        if opts.strict:
            raise FormatUnavailable(
                "mp4 (H.264 + AAC, up to 1080p) cannot satisfy this request "
                "and --strict-format was given"
            )
        if overall_best_h > 1080:
            why = "VP9/AV1 required for >1080p"
        else:
            why = "no H.264/AAC streams available"
        v = max(below, key=_vkey)
        notices.append(switch_notice("mkv", why))
        return _plan(v, best_audio, "mkv", notices)

    if fmt == "mkv":
        prefer_avc = overall_best_h <= 1080
        v = max(below, key=lambda f: _vkey(f, prefer_avc=prefer_avc))
        _note_height(notices, limit, v.height, "mkv")
        return _plan(v, best_audio, "mkv", notices)

    # webm: VP9/AV1 video + Opus audio only (S11)
    web = [f for f in below if f.vfamily in ("vp9", "av1")]
    if web and opus:
        v = max(web, key=_vkey)
        _note_height(notices, limit, v.height, "webm")
        return _plan(v, _best(opus), "webm", notices)
    if opts.strict:
        raise FormatUnavailable(
            "webm (VP9/AV1 + Opus) is not available for this video and --strict-format was given"
        )
    v = max(below, key=lambda f: _vkey(f, prefer_avc=overall_best_h <= 1080))
    notices.append(switch_notice("mkv", "no VP9/AV1 + Opus streams available"))
    return _plan(v, best_audio, "mkv", notices)


def _note_height(notices: list[str], limit: int | None, got: int | None, label: str) -> None:
    if limit is not None and got is not None and got < limit:
        notices.append(f"{limit}p unavailable for {label}, using {got}p")


def _muxed_fallback(usable: Sequence[FormatInfo], opts: VideoOptions) -> VideoPlan:
    """Last resort: a progressive stream that already carries audio and video (e.g. 360p)."""
    muxed = [f for f in usable if f.has_video and f.has_audio and f.height]
    if not muxed:
        raise VideoUnavailable("no downloadable video streams found")
    cap = opts.max_height if opts.max_height is not None else 10**6
    ok = [f for f in muxed if (f.height or 0) <= cap] or [min(muxed, key=lambda f: f.height or 0)]
    f = max(ok, key=lambda m: (m.height or 0, m.tbr or 0.0))
    container = f.ext if f.ext in ("mp4", "mkv", "webm") else "mp4"
    notices = [f"only a combined {f.height}p stream is available"]
    if container != opts.fmt:
        if opts.strict:
            raise FormatUnavailable(
                f"only a {container} stream is available and --strict-format was given"
            )
        notices.append(f"container is {container}, not {opts.fmt}")
    return VideoPlan(f.format_id, container, f.format_id, None, f.height, tuple(notices))
