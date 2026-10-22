"""ffmpeg location, argv construction and execution.

All knowledge of *where* ffmpeg lives is isolated in :func:`locate_ffmpeg`. Today it
prefers ``$PATH``; a later packaging step adds a bundled/cached copy as the fallback
(see ``_bundled_ffmpeg``) without touching any caller.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .errors import InternalError, MissingDependency, ffmpeg_install_hint
from .formats import AudioPlan, Tags
from .options import AudioOptions


def _bundled_ffmpeg() -> Path | None:
    """Seam for the single-binary build: return a bundled/cached ffmpeg, else ``None``."""
    return None


def locate_ffmpeg() -> Path:
    """Return the ffmpeg executable, preferring ``$PATH``; raise exit-5 error if absent."""
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    bundled = _bundled_ffmpeg()
    if bundled is not None and bundled.exists():
        return bundled
    raise MissingDependency("ffmpeg was not found", hint=ffmpeg_install_hint(sys.platform))


def ensure_dependencies() -> None:
    """Startup check for download modes (never called for -h/--version/--list-formats).

    Later: also verify the JavaScript runtime (same exit code 5).
    """
    locate_ffmpeg()


def build_audio_argv(
    src: Path,
    dst: Path,
    plan: AudioPlan,
    opts: AudioOptions,
    meta: Tags,
    *,
    ffmpeg_bin: str | Path = "ffmpeg",
) -> list[str]:
    """Build the ffmpeg argument list (never a shell string) for the audio step.

    ``opts`` is accepted for interface stability; codec arguments are already
    resolved in ``plan``.
    """
    argv: list[str] = [
        str(ffmpeg_bin),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
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
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise InternalError(f"ffmpeg failed (exit {proc.returncode}): " + " | ".join(tail))
