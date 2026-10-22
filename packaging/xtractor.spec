# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-file arm64 macOS Xtractor binary.

Driven by scripts/build_binary.sh, which stages the embedded tools first:

    XTRACTOR_STAGE   directory holding ``xtractor_bundle/`` (manifest.json, ffmpeg, qjs|deno)
    XTRACTOR_VERSION the application version (names nothing here; kept for traceability)

The embedded tools are bytes constants in a generated module (not PyInstaller
"binaries"/"datas"), so PyInstaller never rewrites them and the SHA-256 recorded in the
manifest is the one verified at run time (see src/xtractor/bundle.py).
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH is injected by PyInstaller)
STAGE = Path(os.environ["XTRACTOR_STAGE"]).resolve()
BUNDLE = STAGE / "xtractor_bundle"
assert (BUNDLE / "manifest.json").is_file(), f"stage the tools first: {BUNDLE}"

# yt-dlp-ejs ships the JS challenge solver as package data (spike gotcha 3: mandatory).
ejs_datas, ejs_binaries, ejs_hidden = collect_all("yt_dlp_ejs")

# yt-dlp loads these by name (mirrors yt-dlp's own bundle/pyinstaller.py), and the
# extractor/postprocessor/downloader registries are discovered dynamically.
hidden = [
    "yt_dlp.compat._legacy",
    "yt_dlp.compat._deprecated",
    "yt_dlp.utils._legacy",
    "yt_dlp.utils._deprecated",
    *collect_submodules("yt_dlp", filter=lambda name: "__pyinstaller" not in name),
    *ejs_hidden,
]

# The tools travel inside the generated module xtractor_blob (see release_tools.py), which
# PyInstaller stores in the compressed PYZ: nothing is unpacked per launch.
BLOB_DIR = STAGE / "blob"
assert (BLOB_DIR / "xtractor_blob.py").is_file()
hidden.append("xtractor_blob")
assert (BLOB_DIR / "xtractor_buildinfo.py").is_file()  # versions shown by --version
hidden.append("xtractor_buildinfo")

# Modules the CLI never reaches. Conservative: only things verified absent from any
# code path Xtractor uses (no GUI, no tests, no docs, no cookies/sqlite, no XML-RPC).
excludes = [
    "tkinter",
    "_tkinter",
    "turtle",
    "idlelib",
    "lib2to3",
    "pydoc",
    "pydoc_data",
    "doctest",
    "unittest",
    "test",
    "distutils",
    "setuptools",
    "pkg_resources",
    "pip",
    "xmlrpc",
    "curses",
    "_curses",
    "readline",
    "sqlite3",
    "_sqlite3",
    "mutagen",  # GPL-2.0+; only used by yt-dlp to embed thumbnails, which Xtractor never does
    "websockets",  # live-stream support only
    # Each extension module costs ~15 ms on EVERY --onefile launch (unpacked to a fresh temp
    # dir and checked by macOS), so drop what Xtractor cannot reach:
    "Cryptodome",  # 38 .so files; only for AES-encrypted HLS, yt-dlp falls back to pure Python
    "_codecs_jp",
    "_codecs_kr",
    "_codecs_tw",
    "_codecs_cn",
    "_codecs_hk",
    "_codecs_iso2022",
    # Optional C accelerators / modules with pure-Python or guarded fallbacks, never needed by
    # Xtractor (checked against the modules a real -a run loads). 12 fewer files to unpack.
    "_lzma",
    "lzma",
    "_bz2",
    "bz2",
    "_pickle",
    "_statistics",
    "_sha1",
    "_md5",
    "_sha3",
    "_multiprocessing",
    "_posixshmem",
    "multiprocessing",
    "mmap",
    "resource",
    "grp",
    "numpy",
    "pytest",
    "yt_dlp.__pyinstaller",  # the PyInstaller hook directory, irrelevant at run time
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src"), str(BLOB_DIR)],
    binaries=ejs_binaries,
    datas=ejs_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

ONEDIR = os.environ.get("XTRACTOR_ONEDIR") == "1"  # measurement/fallback layout (BUILD_NOTES.md)

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    *([] if ONEDIR else [a.binaries, a.datas]),
    [],
    exclude_binaries=ONEDIR,
    name="Xtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # strip would invalidate signatures; scripts/sign.sh signs afterwards
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,  # signing is done by scripts/sign.sh (ad hoc, Developer ID later)
    entitlements_file=None,
)

if ONEDIR:
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Xtractor")  # noqa: F821
