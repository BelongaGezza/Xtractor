"""Locate external tools (ffmpeg, JavaScript runtime) and run the startup dependency check.

ffmpeg lookup itself lives in :mod:`xtractor.ffmpeg`; the JavaScript runtime that
yt-dlp needs for YouTube (deno, node, quickjs or bun) is located here. Both prefer
``$PATH`` and keep a ``_bundled_*`` seam for the single-binary build (milestone M10).
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import MissingDependency
from .ffmpeg import locate_ffmpeg

#: (yt-dlp runtime key, executable name) in order of preference.
JS_RUNTIME_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("deno", "deno"),
    ("node", "node"),
    ("quickjs", "qjs"),
    ("bun", "bun"),
)


@dataclass(frozen=True)
class JsRuntime:
    #: yt-dlp ``js_runtimes`` key: deno | node | quickjs | bun
    name: str
    path: Path


@dataclass(frozen=True)
class ToolPaths:
    ffmpeg: Path | None
    js_runtime: JsRuntime | None


def _bundled_js_runtime() -> JsRuntime | None:
    """Seam for the single-binary build: return a bundled/cached runtime, else ``None``."""
    return None


def js_runtime_install_hint(platform: str | None = None) -> str:
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        return "install one with: brew install deno"
    return "install deno (https://deno.com) or Node.js 22+ and make sure it is on your PATH"


def locate_js_runtime() -> JsRuntime:
    """Return a usable JavaScript runtime (``$PATH`` first), or raise exit-5 error."""
    for name, exe in JS_RUNTIME_CANDIDATES:
        found = shutil.which(exe)
        if found:
            return JsRuntime(name, Path(found))
    bundled = _bundled_js_runtime()
    if bundled is not None and bundled.path.exists():
        return bundled
    raise MissingDependency(
        "no JavaScript runtime was found (YouTube extraction needs deno, node, quickjs or bun)",
        hint=js_runtime_install_hint(),
    )


def ensure_dependencies(*, need_ffmpeg: bool, need_js: bool) -> ToolPaths:
    """Startup check, only for operations that really run (never for -h/--version)."""
    ffmpeg = locate_ffmpeg() if need_ffmpeg else None
    js = locate_js_runtime() if need_js else None
    return ToolPaths(ffmpeg=ffmpeg, js_runtime=js)
