"""Locate external tools (ffmpeg, JavaScript runtime) and run the startup dependency check.

ffmpeg lookup itself lives in :mod:`xtractor.ffmpeg`; the JavaScript runtime that
yt-dlp needs for YouTube (deno, node, quickjs or bun) is located here. Both prefer
``$PATH`` outside a bundled build; a bundled build uses its embedded copies first
(``XTRACTOR_USE_SYSTEM_TOOLS=1`` flips the order), see :mod:`xtractor.bundle`.
"""

from __future__ import annotations

import re
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


#: Minimum versions yt-dlp's YouTube support needs (deno/node); quickjs and bun are unchecked.
JS_MIN_VERSIONS: dict[str, tuple[int, int]] = {"deno": (2, 3), "node": (22, 0)}
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


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


def parse_runtime_version(output: str) -> tuple[int, int] | None:
    """``deno 2.3.1 (...)`` or ``v22.4.0`` -> (major, minor)."""
    m = _VERSION_RE.search(output)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _runtime_version(path: str) -> tuple[int, int] | None:
    import subprocess  # lazy: only paid when a PATH runtime is actually used

    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_runtime_version(proc.stdout)


def _system_js_runtime() -> JsRuntime | None:
    """First ``$PATH`` runtime that is new enough; exit 5 if only too-old ones exist."""
    too_old: list[str] = []
    for name, exe in JS_RUNTIME_CANDIDATES:
        found = shutil.which(exe)
        if not found:
            continue
        minimum = JS_MIN_VERSIONS.get(name)
        if minimum is not None:
            version = _runtime_version(found)
            if version is None or version < minimum:
                have = f"{version[0]}.{version[1]}" if version else "unknown version"
                too_old.append(f"{name} {have} (need >= {minimum[0]}.{minimum[1]})")
                continue
        return JsRuntime(name, Path(found))
    if too_old:
        raise MissingDependency(
            "the JavaScript runtime on your PATH is too old: " + "; ".join(too_old),
            hint=js_runtime_install_hint(),
        )
    return None


def locate_js_runtime() -> JsRuntime:
    """Return a usable JavaScript runtime, or raise an exit-5 error.

    Embedded runtime first in a bundled build (else ``$PATH``); with
    ``XTRACTOR_USE_SYSTEM_TOOLS=1`` the ``$PATH`` runtimes come first.
    """
    prefer_system = bundle.use_system_tools()
    too_old: MissingDependency | None = None
    if prefer_system:
        try:
            system = _system_js_runtime()
        except MissingDependency as exc:  # too old: fall back to the embedded one if any
            system, too_old = None, exc
        if system is not None:
            return system
    bundled = _bundled_js_runtime()
    if bundled is not None and bundled.path.exists():
        return bundled
    if not prefer_system:
        system = _system_js_runtime()  # raises exit 5 when only too-old runtimes exist
        if system is not None:
            return system
    if too_old is not None:
        raise too_old
    raise MissingDependency(
        "no JavaScript runtime was found (YouTube extraction needs deno, node, quickjs or bun)",
        hint=js_runtime_install_hint(),
    )


def ensure_dependencies(*, need_ffmpeg: bool, need_js: bool) -> ToolPaths:
    """Startup check, only for operations that really run (never for -h/--version)."""
    ffmpeg = locate_ffmpeg() if need_ffmpeg else None
    js = locate_js_runtime() if need_js else None
    return ToolPaths(ffmpeg=ffmpeg, js_runtime=js)
