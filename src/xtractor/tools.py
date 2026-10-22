"""Locate external tools (ffmpeg, JavaScript runtime) and run the startup dependency check.

ffmpeg lookup itself lives in :mod:`xtractor.ffmpeg`; the JavaScript runtime that
yt-dlp needs for YouTube (deno, node, quickjs or bun) is located here. Both prefer
``$PATH`` outside a bundled build; a bundled build uses its embedded copies first
(``XTRACTOR_USE_SYSTEM_TOOLS=1`` flips the order), see :mod:`xtractor.bundle`.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import bundle
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
    """The embedded JS runtime extracted to the cache, or ``None`` outside a bundled build."""
    found = bundle.bundled_js()
    return JsRuntime(found[0], found[1]) if found else None


def js_runtime_install_hint(platform: str | None = None) -> str:
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        return "install one with: brew install deno"
    return "install deno (https://deno.com) or Node.js 22+ and make sure it is on your PATH"


def _system_js_runtime() -> JsRuntime | None:
    for name, exe in JS_RUNTIME_CANDIDATES:
        found = shutil.which(exe)
        if found:
            return JsRuntime(name, Path(found))
    return None


def locate_js_runtime() -> JsRuntime:
    """Return a usable JavaScript runtime, or raise an exit-5 error.

    Embedded runtime first in a bundled build (else ``$PATH``); with
    ``XTRACTOR_USE_SYSTEM_TOOLS=1`` the ``$PATH`` runtimes come first.
    """
    system = _system_js_runtime()
    if bundle.use_system_tools() and system is not None:
        return system
    bundled = _bundled_js_runtime()
    if bundled is not None and bundled.path.exists():
        return bundled
    if system is not None:
        return system
    raise MissingDependency(
        "no JavaScript runtime was found (YouTube extraction needs deno, node, quickjs or bun)",
        hint=js_runtime_install_hint(),
    )


def ensure_dependencies(*, need_ffmpeg: bool, need_js: bool) -> ToolPaths:
    """Startup check, only for operations that really run (never for -h/--version)."""
    ffmpeg = locate_ffmpeg() if need_ffmpeg else None
    js = locate_js_runtime() if need_js else None
    return ToolPaths(ffmpeg=ffmpeg, js_runtime=js)
