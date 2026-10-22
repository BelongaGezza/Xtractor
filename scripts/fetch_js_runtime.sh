#!/usr/bin/env bash
# Fetch the pinned, checksum-verified arm64 JS runtime that yt-dlp needs for YouTube.
#   RUNTIME=quickjs-ng (default) | deno
# Output: build/js/qjs (or build/js/deno) and build/BUILDINFO-js.json
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

RUNTIME="${RUNTIME:-quickjs-ng}"

QJS_VERSION=0.17.0
QJS_SHA256=8be3ddfe3397d2e692e4e1e8972ee9d032a0a580505d2f8b4ea528cf1b651c11
QJS_URL="https://github.com/quickjs-ng/quickjs/releases/download/v$QJS_VERSION/qjs-darwin-arm64"

DENO_VERSION=2.9.8
DENO_ZIP_SHA256=9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e
DENO_URL="https://github.com/denoland/deno/releases/download/v$DENO_VERSION/deno-aarch64-apple-darwin.zip"

OUT="$BUILD_DIR/js"
rm -rf "$OUT"; mkdir -p "$OUT" "$BUILD_DIR/src"

case "$RUNTIME" in
  quickjs-ng|quickjs|qjs)
    RUNTIME=quickjs-ng; NAME=quickjs; EXE=qjs; VERSION=$QJS_VERSION; URL=$QJS_URL; SHA=$QJS_SHA256
    fetch_verified "$URL" "$BUILD_DIR/src/qjs-darwin-arm64-$VERSION" "$SHA"
    cp "$BUILD_DIR/src/qjs-darwin-arm64-$VERSION" "$OUT/qjs"
    ;;
  deno)
    NAME=deno; EXE=deno; VERSION=$DENO_VERSION; URL=$DENO_URL; SHA=$DENO_ZIP_SHA256
    fetch_verified "$URL" "$BUILD_DIR/src/deno-$VERSION-aarch64-apple-darwin.zip" "$SHA"
    unzip -qo "$BUILD_DIR/src/deno-$VERSION-aarch64-apple-darwin.zip" deno -d "$OUT"
    ;;
  *) die "unknown RUNTIME '$RUNTIME' (quickjs-ng|deno)" ;;
esac

chmod +x "$OUT/$EXE"
codesign --force -s - "$OUT/$EXE" 2>/dev/null || true
file "$OUT/$EXE" | grep -q arm64 || die "$EXE is not an arm64 Mach-O"
if [ "$NAME" = deno ]; then
  GOT="$("$OUT/$EXE" --version | head -1 | awk '{print $2}')"
  [ "$GOT" = "$VERSION" ] || die "deno --version says $GOT, expected $VERSION"
else
  "$OUT/$EXE" --help 2>&1 | grep -q "QuickJS-ng version $VERSION" || die "qjs version mismatch (want $VERSION)"
fi

cat >"$BUILD_DIR/BUILDINFO-js.json" <<JSON
{
  "runtime": "$RUNTIME",
  "yt_dlp_name": "$NAME",
  "executable": "$EXE",
  "version": "$VERSION",
  "url": "$URL",
  "download_sha256": "$SHA",
  "sha256": "$(sha256_of "$OUT/$EXE")",
  "size_bytes": $(stat -f %z "$OUT/$EXE")
}
JSON
log "runtime ready: $OUT/$EXE ($RUNTIME $VERSION)"
