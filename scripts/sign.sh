#!/usr/bin/env bash
# Sign the Xtractor binary.  Usage: scripts/sign.sh PATH_TO_BINARY
#
#   SIGN_IDENTITY unset or "-"   ad-hoc signature (decision P1, the default, free).
#   SIGN_IDENTITY="Developer ID Application: ..."   Developer ID path (UNTESTED: no identity
#       was available when this was written): hardened runtime + secure timestamp + the
#       entitlements the PyInstaller bootloader needs; set NOTARY_PROFILE (a notarytool
#       keychain profile) to also submit for notarization and wait for the verdict.
#
# The embedded ffmpeg/qjs are signed before they are embedded (build_ffmpeg.sh and
# fetch_js_runtime.sh); the extracted cache copies keep those signatures. A Developer ID
# build must sign them with the same identity BEFORE build_binary.sh embeds them.
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

BIN="${1:-}"
[ -f "$BIN" ] || die "usage: sign.sh BINARY"
IDENTITY="${SIGN_IDENTITY:--}"

if [ "$IDENTITY" = "-" ]; then
  log "ad-hoc signing $BIN"
  codesign --force --sign - "$BIN"
else
  log "Developer ID signing $BIN as '$IDENTITY'"
  codesign --force --timestamp --options runtime \
    --entitlements "$REPO_ROOT/packaging/entitlements.plist" --sign "$IDENTITY" "$BIN"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    zip="$(mktemp -d)/Xtractor.zip"
    ditto -c -k --keepParent "$BIN" "$zip"
    xcrun notarytool submit "$zip" --keychain-profile "$NOTARY_PROFILE" --wait
    spctl -a -vv -t exec "$BIN" || true
  fi
fi

codesign --verify --strict --verbose=1 "$BIN"
codesign -dv "$BIN" 2>&1 | grep -E "Signature|Identifier|flags" || true
