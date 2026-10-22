"""Option validation and defaults resolution (S1, S3, S6, S9). No I/O beyond ``Path.is_dir``."""

from __future__ import annotations

import re
from argparse import Namespace
from dataclasses import dataclass
from typing import Literal, cast

from .errors import UsageError
from .paths import looks_like_file, validate_template
from .urls import VideoRef, parse_youtube_url

SAMPLE_RATES: tuple[int, ...] = (22050, 32000, 44100, 48000, 88200, 96000)
AUDIO_FORMATS: tuple[str, ...] = ("m4a", "mp3", "opus", "flac", "wav")
VIDEO_FORMATS: tuple[str, ...] = ("mp4", "mkv", "webm")
RESOLUTIONS: tuple[str, ...] = ("360", "480", "720", "1080", "1440", "2160", "best")

DEFAULT_SAMPLE_RATE = 44100
OPUS_SAMPLE_RATE = 48000
MP3_MAX_SAMPLE_RATE = 48000
DEFAULT_AUDIO_FORMAT = "m4a"
DEFAULT_BITRATE = "128k"
DEFAULT_RESOLUTION = "1080"
DEFAULT_VIDEO_FORMAT = "mp4"
DEFAULT_TEMPLATE = "%(title)s"

AudioFmt = Literal["m4a", "mp3", "opus", "flac", "wav"]
VideoFmt = Literal["mp4", "mkv", "webm"]
Mode = Literal["audio", "video"]

_BITRATE_RE = re.compile(r"^\d{2,3}k$")

_AUDIO_FLAGS = (
    ("sample_rate", "--sample-rate"),
    ("audio_format", "--audio-format"),
    ("audio_quality", "--audio-quality"),
)
_VIDEO_FLAGS = (
    ("resolution", "--resolution"),
    ("video_format", "--video-format"),
    ("strict_format", "--strict-format"),
)


@dataclass(frozen=True)
class AudioOptions:
    sample_rate: int
    fmt: AudioFmt
    #: ``None`` means "not requested": the m4a path may then stream-copy (S1).
    bitrate: str | None


@dataclass(frozen=True)
class VideoOptions:
    #: ``None`` means ``best``.
    max_height: int | None
    fmt: VideoFmt
    strict: bool


@dataclass(frozen=True)
class Options:
    mode: Mode | None
    url: VideoRef
    output: str | None
    output_is_file: bool
    name_template: str
    overwrite: bool
    quiet: bool
    verbose: bool
    list_formats: bool
    audio: AudioOptions | None
    video: VideoOptions | None
    #: User-facing warnings produced during validation (printed by the reporter).
    warnings: tuple[str, ...] = ()


def _given(ns: Namespace, dest: str) -> bool:
    value = getattr(ns, dest, None)
    return value is not None and value is not False


def _resolve_audio(ns: Namespace, warnings: list[str]) -> AudioOptions:
    fmt_raw = ns.audio_format if ns.audio_format is not None else DEFAULT_AUDIO_FORMAT
    fmt_l = str(fmt_raw).lower()
    if fmt_l not in AUDIO_FORMATS:
        raise UsageError(
            f"invalid --audio-format {fmt_raw!r}; valid formats: {', '.join(AUDIO_FORMATS)}"
        )
    fmt = cast(AudioFmt, fmt_l)  # validated against AUDIO_FORMATS above

    rate = DEFAULT_SAMPLE_RATE
    if ns.sample_rate is not None:
        try:
            rate = int(str(ns.sample_rate))
        except ValueError:
            rate = -1
        if rate not in SAMPLE_RATES:
            raise UsageError(
                f"invalid --sample-rate {ns.sample_rate!r}; valid rates (Hz): "
                f"{', '.join(map(str, SAMPLE_RATES))}"
            )
        if fmt == "opus" and rate != OPUS_SAMPLE_RATE:
            raise UsageError(
                f"--audio-format opus always runs at {OPUS_SAMPLE_RATE} Hz; "
                f"--sample-rate {rate} is not allowed (omit it or use {OPUS_SAMPLE_RATE})"
            )
        if fmt == "mp3" and rate > MP3_MAX_SAMPLE_RATE:
            raise UsageError(
                f"--audio-format mp3 supports at most {MP3_MAX_SAMPLE_RATE} Hz; "
                f"--sample-rate {rate} is not allowed"
            )
        if rate > 48000:
            warnings.append(
                f"source audio is at most 48 kHz; {rate} Hz output will be upsampled "
                "(no added fidelity)"
            )
    elif fmt == "opus":
        rate = OPUS_SAMPLE_RATE

    bitrate: str | None = None
    if ns.audio_quality is not None:
        bitrate = str(ns.audio_quality).lower()
        if not _BITRATE_RE.match(bitrate):
            raise UsageError(
                f"invalid --audio-quality {ns.audio_quality!r}; "
                "use a bitrate such as 128k, 192k, 256k or 320k"
            )
        if fmt in ("flac", "wav"):
            warnings.append(f"--audio-quality is ignored for lossless {fmt} output")
            bitrate = None
    return AudioOptions(sample_rate=rate, fmt=fmt, bitrate=bitrate)


def _resolve_video(ns: Namespace) -> VideoOptions:
    res = str(ns.resolution if ns.resolution is not None else DEFAULT_RESOLUTION).lower()
    if res not in RESOLUTIONS:
        raise UsageError(
            f"invalid --resolution {ns.resolution!r}; valid values: {', '.join(RESOLUTIONS)}"
        )
    fmt_l = str(ns.video_format if ns.video_format is not None else DEFAULT_VIDEO_FORMAT).lower()
    if fmt_l not in VIDEO_FORMATS:
        raise UsageError(
            f"invalid --video-format {ns.video_format!r}; valid formats: {', '.join(VIDEO_FORMATS)}"
        )
    fmt = cast(VideoFmt, fmt_l)  # validated against VIDEO_FORMATS above
    return VideoOptions(
        max_height=None if res == "best" else int(res),
        fmt=fmt,
        strict=bool(ns.strict_format),
    )


def build_options(ns: Namespace) -> Options:
    """Validate a parsed namespace and resolve defaults. Raises :class:`UsageError`."""
    if ns.quiet and ns.verbose:
        raise UsageError("-q/--quiet and --verbose cannot be used together")

    want_audio, want_video = bool(ns.audio), bool(ns.video)
    if want_audio and want_video:
        raise UsageError("-a/--audio and -v/--video are mutually exclusive; choose one")
    mode: Mode | None = "audio" if want_audio else "video" if want_video else None
    if mode is None and not ns.list_formats:
        raise UsageError("exactly one of -a/--audio or -v/--video is required")

    if mode != "audio":
        for dest, flag in _AUDIO_FLAGS:
            if _given(ns, dest):
                raise UsageError(f"{flag} is an audio option and requires -a/--audio")
    if mode != "video":
        for dest, flag in _VIDEO_FLAGS:
            if _given(ns, dest):
                raise UsageError(f"{flag} is a video option and requires -v/--video")

    if ns.url is None:
        raise UsageError("a YouTube URL is required")
    ref = parse_youtube_url(ns.url)

    warnings: list[str] = []
    audio = _resolve_audio(ns, warnings) if mode == "audio" else None
    video = _resolve_video(ns) if mode == "video" else None

    template = DEFAULT_TEMPLATE
    output_is_file = False
    if ns.output is not None:
        if not str(ns.output).strip():
            raise UsageError("--output must not be empty")
        output_is_file = looks_like_file(str(ns.output))
    if ns.name is not None:
        if output_is_file:
            raise UsageError("--name cannot be combined with -o/--output pointing at a file")
        validate_template(ns.name)
        template = ns.name

    if output_is_file and not ns.list_formats:
        suffix = "." + str(ns.output).rsplit(".", 1)[-1].lower()
        expected_fmt = audio.fmt if audio else video.fmt if video else None
        if expected_fmt is not None and suffix != f".{expected_fmt}":
            flag = "--audio-format" if audio else "--video-format"
            raise UsageError(
                f"-o/--output extension '{suffix}' does not match {flag} {expected_fmt} "
                f"(expected '.{expected_fmt}')"
            )

    return Options(
        mode=mode,
        url=ref,
        output=ns.output,
        output_is_file=output_is_file,
        name_template=template,
        overwrite=bool(ns.overwrite),
        quiet=bool(ns.quiet),
        verbose=bool(ns.verbose),
        list_formats=bool(ns.list_formats),
        audio=audio,
        video=video,
        warnings=tuple(warnings),
    )
