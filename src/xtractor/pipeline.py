"""Orchestration: probe -> select -> download -> post-process -> atomic move.

Nothing here prints to stdout; :func:`run` returns the final path and ``cli`` prints it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import InternalError
from .ffmpeg import build_audio_argv
from .formats import (
    AudioPlan,
    FormatInfo,
    MediaInfo,
    Tags,
    VideoPlan,
    check_playable,
    select_audio,
    select_video,
)
from .options import Options
from .paths import atomic_move, resolve_output, should_skip, temp_workdir
from .ui import Reporter, human_size
from .urls import VideoRef
from .ytdlp import OUTTMPL, Extractor

_NOMINAL_NOTE = re.compile(r"^\d{3,4}p")
OUT_STEM = "xtractor-out"


@dataclass
class Deps:
    """Everything ``run`` needs from the outside world (injected by tests)."""

    extractor: Extractor
    reporter: Reporter
    run_ffmpeg: Callable[[Sequence[str]], None]
    ffmpeg_bin: str | Path = "ffmpeg"
    cwd: Path | None = None


def _missing_dirs(directory: Path) -> list[Path]:
    """Directories that do not exist yet, shallowest first."""
    missing: list[Path] = []
    cur = directory
    while not cur.exists() and cur != cur.parent:
        missing.append(cur)
        cur = cur.parent
    return missing[::-1]


def _remove_created(dirs: Sequence[Path]) -> None:
    for d in reversed(dirs):
        try:
            d.rmdir()
        except OSError:
            break


def run(opts: Options, deps: Deps) -> Path:
    """Download one video as audio or video and return the final file path."""
    rep = deps.reporter
    ref: VideoRef = opts.url
    rep.info(f"Fetching video information for {ref.video_id} ...")
    info = deps.extractor.probe(ref)
    check_playable(info)

    plan: AudioPlan | VideoPlan
    if opts.mode == "audio" and opts.audio is not None:
        plan = select_audio(info.formats, opts.audio)
        ext, selector, merge_to, resolution = plan.ext, plan.format_id, None, None
    elif opts.mode == "video" and opts.video is not None:
        plan = select_video(info.formats, opts.video)
        ext, selector, merge_to = plan.container, plan.format_selector, plan.container
        resolution = f"{plan.height}p" if plan.height else None
    else:  # pragma: no cover - guarded by option validation
        raise InternalError("no download mode selected")
    for notice in plan.notices:
        rep.notice(notice)

    final = resolve_output(
        opts.output,
        output_is_file=opts.output_is_file,
        template=opts.name_template,
        fields={
            "title": info.title,
            "id": info.id or ref.video_id,
            "uploader": info.uploader,
            "upload_date": info.upload_date,
            "resolution": resolution,
        },
        ext=ext,
        cwd=deps.cwd,
    )
    if should_skip(final, overwrite=opts.overwrite):
        rep.info(f"{final} exists, skipping (use --overwrite to replace it)")
        return final

    created = _missing_dirs(final.parent)
    try:
        with temp_workdir(final.parent) as tmp:
            rep.info(f"Downloading {info.title or ref.video_id} ...")
            rep.reset_progress()
            downloaded = deps.extractor.download(
                ref, selector, tmp, OUTTMPL, merge_to, rep.progress
            )
            rep.reset_progress()
            if isinstance(plan, AudioPlan):
                assert opts.audio is not None
                produced = tmp / f"{OUT_STEM}.{ext}"
                rep.info("Copying audio stream ..." if plan.copy else "Converting audio ...")
                argv = build_audio_argv(
                    downloaded,
                    produced,
                    plan,
                    Tags.from_media(info, ref.canonical_url),
                    ffmpeg_bin=deps.ffmpeg_bin,
                )
                deps.run_ffmpeg(argv)
            else:
                produced = downloaded
                if produced.suffix.lower() != f".{ext}":
                    raise InternalError(
                        f"downloaded file is {produced.suffix!r} but {ext!r} was expected"
                    )
            atomic_move(produced, final)
    except BaseException:
        _remove_created(created)
        raise
    rep.info(f"Saved {final}")
    return final


# ------------------------------------------------------------------ --list-formats
def _res(f: FormatInfo) -> str:
    if f.audio_only:
        return "audio only"
    return f"{f.height}p" if f.height else "?"


def format_table(info: MediaInfo) -> str:
    """Plain-text table of the streams of ``info`` (storyboards omitted)."""
    header = ("ID", "EXT", "RES", "FPS", "VCODEC", "ACODEC", "RATE", "SIZE", "NOTES")
    rows: list[tuple[str, ...]] = [header]
    for f in info.formats:
        if not (f.has_video or f.has_audio):
            continue
        notes = [n for n in (f.note, "video only" if f.video_only else "") if n]
        notes = [n for n in notes if not _NOMINAL_NOTE.match(n)]
        if f.has_drm:
            notes.append("DRM")
        rows.append(
            (
                f.format_id,
                f.ext,
                _res(f),
                f"{f.fps:g}" if f.fps else "",
                f.vcodec if f.has_video else "",
                f.acodec if f.has_audio else "",
                f"{f.asr}" if f.asr else "",
                human_size(f.filesize) if f.filesize else "",
                ", ".join(notes),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    return "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows)


def list_formats(opts: Options, deps: Deps) -> str:
    """Probe and render the format table (no ffmpeg, no files)."""
    info = deps.extractor.probe(opts.url)
    return format_table(info)
