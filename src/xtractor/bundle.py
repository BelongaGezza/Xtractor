"""Embedded tools of the single-binary build: manifest, one-time extraction, verification.

A PyInstaller build embeds the ``ffmpeg`` and JS-runtime executables plus a manifest
inside a generated Python module (``xtractor_blob``) so they live in the compressed
PYZ archive and are NOT unpacked to a temp directory on every launch (that unpacking is
what makes ``--onefile`` slow). Tests and tooling may instead point ``XTRACTOR_BUNDLE_DIR``
at a directory holding ``manifest.json`` and the executables. On first use the executables are
copied to ``~/Library/Caches/Xtractor/<version>-<sha8>/`` and reused on later runs. Every
start verifies the SHA-256 of the file it is about to use and re-extracts once if it
is missing or damaged. In a normal (non-frozen) run there is no bundle and every
function here reports "nothing bundled".

Environment: ``XTRACTOR_CACHE_DIR`` overrides the cache root (tests, sandboxes);
``XTRACTOR_BUNDLE_DIR`` points at a bundle directory instead of the embedded blob (tests).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import MissingDependency

BLOB_MODULE = "xtractor_blob"
MANIFEST_NAME = "manifest.json"
ENV_CACHE_DIR = "XTRACTOR_CACHE_DIR"
ENV_BUNDLE_DIR = "XTRACTOR_BUNDLE_DIR"
ENV_USE_SYSTEM = "XTRACTOR_USE_SYSTEM_TOOLS"

_HINT = f"set {ENV_USE_SYSTEM}=1 to use ffmpeg and a JavaScript runtime from your PATH instead"


@dataclass(frozen=True)
class Asset:
    name: str  # file name inside the bundle and in the cache
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    app_version: str
    assets: dict[str, Asset]
    #: yt-dlp ``js_runtimes`` key of the embedded runtime (``quickjs`` or ``deno``) and its asset.
    js_name: str | None
    js_asset: str | None

    @property
    def digest8(self) -> str:
        """First 8 hex chars of the SHA-256 over the sorted ``name:sha256`` lines."""
        joined = "\n".join(f"{a.name}:{a.sha256}" for a in sorted(self.assets.values(), key=_name))
        return hashlib.sha256(joined.encode()).hexdigest()[:8]

    @property
    def cache_key(self) -> str:
        return f"{self.app_version}-{self.digest8}"


def _name(asset: Asset) -> str:
    return asset.name


def use_system_tools() -> bool:
    """``XTRACTOR_USE_SYSTEM_TOOLS=1`` opts in to ``$PATH`` tools ahead of the embedded ones."""
    return os.environ.get(ENV_USE_SYSTEM) == "1"


class Source(Protocol):
    """Where the embedded files come from: the frozen blob module, or a directory (tests)."""

    def manifest_text(self) -> str: ...

    def read(self, name: str) -> bytes: ...


@dataclass(frozen=True)
class DirSource:
    directory: Path

    def manifest_text(self) -> str:
        return (self.directory / MANIFEST_NAME).read_text()

    def read(self, name: str) -> bytes:
        return (self.directory / name).read_bytes()


@dataclass(frozen=True)
class BlobSource:
    """The generated ``xtractor_blob`` module: ``MANIFEST`` (JSON text) and ``FILES`` (bytes)."""

    module: _BlobModule

    def manifest_text(self) -> str:
        return self.module.MANIFEST

    def read(self, name: str) -> bytes:
        return self.module.FILES[name]


class _BlobModule(Protocol):
    MANIFEST: str
    FILES: dict[str, bytes]


def bundle_source() -> Source | None:
    """The embedded-files source, or ``None`` outside a bundled build."""
    override = os.environ.get(ENV_BUNDLE_DIR)
    if override:
        p = Path(override)
        return DirSource(p) if (p / MANIFEST_NAME).is_file() else None
    if not getattr(sys, "frozen", False):
        return None
    try:
        return BlobSource(importlib.import_module(BLOB_MODULE))
    except ImportError:
        return None


def load_manifest(source: Source) -> Manifest:
    try:
        raw = json.loads(source.manifest_text())
        assets = {
            key: Asset(str(v["name"]), str(v["sha256"]), int(v["size"]))
            for key, v in raw["assets"].items()
        }
        js = raw.get("js") or {}
        return Manifest(
            app_version=str(raw["app_version"]),
            assets=assets,
            js_name=str(js["name"]) if js else None,
            js_asset=str(js["asset"]) if js else None,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MissingDependency(
            f"the embedded tool manifest is unreadable ({exc})", hint=_HINT
        ) from exc


def cache_root() -> Path:
    override = os.environ.get(ENV_CACHE_DIR)
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Xtractor"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "Xtractor"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_valid(path: Path, asset: Asset) -> bool:
    try:
        return (
            path.is_file()
            and path.stat().st_size == asset.size
            and os.access(path, os.X_OK)
            and file_sha256(path) == asset.sha256
        )
    except OSError:
        return False


def _adhoc_sign_if_needed(path: Path) -> None:
    """Re-apply an ad-hoc signature when the copy no longer verifies (arm64 kills unsigned code)."""
    if sys.platform != "darwin" or shutil.which("codesign") is None:
        return
    try:
        ok = subprocess.run(
            ["codesign", "--verify", str(path)], capture_output=True, check=False, timeout=30
        ).returncode
        if ok != 0:
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(path)],
                capture_output=True,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.SubprocessError):
        pass


def _install(data: bytes, dst: Path, asset: Asset) -> None:
    """Atomically place a verified copy of ``data`` at ``dst`` (temp file + ``os.replace``)."""
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise OSError(f"embedded {asset.name} does not match its recorded checksum")
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        _adhoc_sign_if_needed(tmp)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_extracted(key: str, source: Source | None = None) -> Path:
    """Return the path of bundled asset ``key`` in the cache, extracting it if needed.

    Raises :class:`MissingDependency` (exit 5) when it cannot be provided. Returns
    quickly for the common case: the file exists and its hash matches.
    """
    src = source if source is not None else bundle_source()
    if src is None:
        raise MissingDependency("no embedded tools in this build", hint=_HINT)
    manifest = load_manifest(src)
    asset = manifest.assets.get(key)
    if asset is None:
        raise MissingDependency(f"{key} is not part of this build", hint=_HINT)
    cache = cache_root() / manifest.cache_key
    dst = cache / asset.name
    if _is_valid(dst, asset):
        return dst
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        _install(src.read(asset.name), dst, asset)
    except (OSError, KeyError) as exc:
        raise MissingDependency(
            f"could not extract the embedded {asset.name} to {cache} ({exc})", hint=_HINT
        ) from exc
    if not _is_valid(dst, asset):  # lost a race with a corrupting writer, or a bad disk
        raise MissingDependency(f"the extracted {asset.name} failed verification", hint=_HINT)
    return dst


def bundled_asset_path(key: str) -> Path | None:
    """Path of an extracted bundled asset, or ``None`` when this build has no bundle."""
    src = bundle_source()
    if src is None:
        return None
    if key not in load_manifest(src).assets:
        return None
    return ensure_extracted(key, src)


def bundled_js() -> tuple[str, Path] | None:
    """(yt-dlp runtime key, extracted path) of the embedded JS runtime, or ``None``."""
    src = bundle_source()
    if src is None:
        return None
    manifest = load_manifest(src)
    if manifest.js_name is None or manifest.js_asset is None:
        return None
    return manifest.js_name, ensure_extracted(manifest.js_asset, src)
