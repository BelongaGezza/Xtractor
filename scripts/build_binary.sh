#!/usr/bin/env bash
# Build the single-file arm64 macOS binary.
#
# Outputs (in dist/):
#   Xtractor                             the ad-hoc signed executable
#   Xtractor-<version>-macos-arm64.tar.gz   Xtractor + LICENSE + THIRD_PARTY_NOTICES
#   SHA256SUMS                           checksum of the tarball (what --self-update verifies)
#
# Environment:
#   RUNTIME=quickjs-ng|deno   embedded JS runtime (default quickjs-ng)
#   VERSION=x.y.z             override the version taken from src/xtractor/__init__.py
#   PYTHON=...                interpreter with the project and `.[build]` installed (default .venv)
#   SIGN_IDENTITY             see scripts/sign.sh (default: ad hoc)
#   SOURCE_DATE_EPOCH         timestamp for the tarball (default 0, reproducible)
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || die "the binary is built on arm64 macOS only"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
RUNTIME="${RUNTIME:-quickjs-ng}"
VERSION="${VERSION:-$(app_version)}"
[ -n "$VERSION" ] || die "cannot determine the version"
DIST="$REPO_ROOT/dist"
STAGE="$BUILD_DIR/stage"
WORKPATH="$BUILD_DIR/pyinstaller"

"$PYTHON" -c "import PyInstaller, yt_dlp, yt_dlp_ejs" 2>/dev/null \
  || die "$PYTHON lacks PyInstaller/yt-dlp: pip install -e '.[build]'"
"$PYTHON" -c "import sys; assert sys.version_info[:2] >= (3, 12)" || die "build with Python 3.12+"

[ -x "$BUILD_DIR/ffmpeg" ] || "$REPO_ROOT/scripts/build_ffmpeg.sh"
if [ ! -f "$BUILD_DIR/BUILDINFO-js.json" ] || ! grep -q "\"runtime\": \"$RUNTIME\"" "$BUILD_DIR/BUILDINFO-js.json"; then
  RUNTIME="$RUNTIME" "$REPO_ROOT/scripts/fetch_js_runtime.sh"
fi
JS_EXE="$("$PYTHON" -c "import json; print(json.load(open('$BUILD_DIR/BUILDINFO-js.json'))['executable'])")"
JS_NAME="$("$PYTHON" -c "import json; print(json.load(open('$BUILD_DIR/BUILDINFO-js.json'))['yt_dlp_name'])")"

log "staging embedded tools (ffmpeg + $JS_EXE)"
rm -rf "$STAGE"; mkdir -p "$STAGE"
"$PYTHON" "$REPO_ROOT/scripts/release_tools.py" manifest "$STAGE" "$VERSION" \
  "$BUILD_DIR/ffmpeg" "$BUILD_DIR/js/$JS_EXE" "$JS_NAME"

"$PYTHON" "$REPO_ROOT/scripts/release_tools.py" buildinfo "$STAGE" \
  "$BUILD_DIR/BUILDINFO-ffmpeg.json" "$BUILD_DIR/BUILDINFO-js.json"

log "running PyInstaller (onefile, arm64)"
rm -rf "$DIST" "$WORKPATH"
XTRACTOR_STAGE="$STAGE" XTRACTOR_VERSION="$VERSION" \
  "$PYTHON" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath "$DIST" --workpath "$WORKPATH" "$REPO_ROOT/packaging/xtractor.spec"

BIN="$DIST/Xtractor"
[ -f "$BIN" ] || die "PyInstaller did not produce $BIN"
file "$BIN" | grep -q "arm64" || die "$BIN is not an arm64 executable"
"$REPO_ROOT/scripts/sign.sh" "$BIN"

log "packaging"
TARBALL="Xtractor-$VERSION-macos-arm64.tar.gz"
"$PYTHON" "$REPO_ROOT/scripts/release_tools.py" tarball "$DIST/$TARBALL" "$BIN" \
  "$REPO_ROOT/LICENSE" "$REPO_ROOT/THIRD_PARTY_NOTICES"
( cd "$DIST" && shasum -a 256 "$TARBALL" > SHA256SUMS )

cp "$BUILD_DIR"/BUILDINFO-*.json "$DIST/" 2>/dev/null || true
log "built $BIN ($(stat -f %z "$BIN") bytes), $DIST/$TARBALL ($(stat -f %z "$DIST/$TARBALL") bytes)"
cat "$DIST/SHA256SUMS"
