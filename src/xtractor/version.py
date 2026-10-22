"""Version text for ``--version``: Xtractor plus the tools it bundles (no subprocess).

A single-file build embeds a tiny generated module ``xtractor_buildinfo`` with a
``VERSIONS`` dict (``{"yt-dlp": ..., "ffmpeg": ..., "deno" | "quickjs": ...}``) written at
build time, so printing the versions costs nothing. Source installs fall back to the
installed yt-dlp distribution's metadata and do not claim anything about ffmpeg or the
JavaScript runtime (those come from ``$PATH`` there).
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
from typing import Any

from . import __version__

BUILDINFO_MODULE = "xtractor_buildinfo"
_ORDER = ("yt-dlp", "ffmpeg", "deno", "quickjs", "node", "bun")


def _buildinfo() -> dict[str, str]:
    try:
        module: Any = importlib.import_module(BUILDINFO_MODULE)
        return {str(k): str(v) for k, v in dict(module.VERSIONS).items()}
    except (ImportError, AttributeError, TypeError, ValueError):
        return {}


def _installed_ytdlp_version() -> str | None:
    """Read yt-dlp's version file without importing yt-dlp (or importlib.metadata)."""
    try:
        spec = importlib.util.find_spec("yt_dlp")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for base in spec.submodule_search_locations:
        try:
            text = (Path(base) / "version.py").read_text()
        except OSError:
            continue
        m = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", text)
        if m:
            return m.group(1)
    return None


def tool_versions() -> dict[str, str]:
    """Versions of yt-dlp and the embedded tools that are known without running anything."""
    versions = _buildinfo()
    if "yt-dlp" not in versions:
        found = _installed_ytdlp_version()
        if found:
            versions["yt-dlp"] = found
    return versions


def version_text() -> str:
    """``Xtractor X.Y.Z`` on the first line, then one ``name version`` line per known tool."""
    versions = tool_versions()
    names = [n for n in _ORDER if n in versions] + sorted(n for n in versions if n not in _ORDER)
    return "\n".join([f"Xtractor {__version__}", *(f"{n} {versions[n]}" for n in names)])
