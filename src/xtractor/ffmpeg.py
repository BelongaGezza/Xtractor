"""ffmpeg location, argv construction and execution.

All knowledge of *where* ffmpeg lives is isolated in :func:`locate_ffmpeg`. In a
bundled (single-binary) build the embedded copy, extracted once to the cache, is used
first so behaviour is reproducible; ``XTRACTOR_USE_SYSTEM_TOOLS=1`` prefers ``$PATH``.
Outside a bundled build only ``$PATH`` is used.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from . import bundle
from .errors import FileSystemError, InternalError, MissingDependency, ffmpeg_install_hint
from .formats import AudioPlan, Tags


def locate_ffmpeg() -> Path:
    """Return the ffmpeg executable; raise an exit-5 error if there is none.

    Order: embedded copy first (bundled builds), else ``$PATH``; with
    ``XTRACTOR_USE_SYSTEM_TOOLS=1`` ``$PATH`` comes first and the embedded copy is the fallback.
    """
    system = shutil.which("ffmpeg")
    if bundle.use_system_tools() and system:
        return Path(system)
    bundled = bundle.bundled_asset_path("ffmpeg")  # None outside a bundled build
    if bundled is not None and bundled.exists():
        return bundled
    if system:
        return Path(system)
    raise MissingDependency("ffmpeg was not found", hint=ffmpeg_install_hint(sys.platform))


def build_audio_argv(
    src: Path,
    dst: Path,
    plan: AudioPlan,
    meta: Tags,
    *,
    ffmpeg_bin: str | Path = "ffmpeg",
) -> list[str]:
    """Build the ffmpeg argument list (never a shell string) for the audio step.

    Codec arguments are already resolved in ``plan``.
    """
    argv: list[str] = [
        str(ffmpeg_bin),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(src),
        "-vn",
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        *plan.ffmpeg_codec_args,
    ]
    if plan.ext == "mp3":
        argv += ["-id3v2_version", "3"]
    for key, value in (
        ("title", meta.title),
        ("artist", meta.artist),
        ("date", meta.date),
        ("comment", meta.url),
    ):
        if value:
            argv += ["-metadata", f"{key}={value}"]
    argv.append(str(dst))
    return argv


def run_ffmpeg(argv: Sequence[str], *, verbose: bool = False) -> None:
    """Run ffmpeg without a shell; stdout discarded, stderr captured."""
    if verbose:
        print(f"+ {shlex.join(argv)}", file=sys.stderr)
    try:
        proc = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MissingDependency("ffmpeg was not found", hint=ffmpeg_install_hint()) from exc
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        low = stderr.lower()
        if "unknown encoder" in low or ("encoder" in low and "not found" in low):
            raise MissingDependency(
                "your ffmpeg build lacks a required encoder", hint="install a full ffmpeg build"
            )
        if "no space left on device" in low:
            raise FileSystemError("no space left on device")
        tail = stderr.strip().splitlines()[-5:]
        raise InternalError(f"ffmpeg failed (exit {proc.returncode}): " + " | ".join(tail))
