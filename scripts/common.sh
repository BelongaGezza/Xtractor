# Shared helpers, sourced by the other scripts. Not executable on its own.
# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build}"

# The scripts `rm -rf` paths below BUILD_DIR: refuse anything that is not a deep absolute path.
case "$BUILD_DIR" in
  /?*/?*) ;;
  *) echo "error: BUILD_DIR must be an absolute path at least two levels deep: '$BUILD_DIR'" >&2; exit 1 ;;
esac

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*" >&2; }

sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }

# fetch_verified URL DEST SHA256 : download (if absent or wrong) and verify.
fetch_verified() {
  local url="$1" dest="$2" want="$3" got
  if [ -f "$dest" ] && [ "$(sha256_of "$dest")" = "$want" ]; then return 0; fi
  log "downloading $url"
  mkdir -p "$(dirname "$dest")"
  curl -fsSL --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 -o "$dest.part" "$url"
  got="$(sha256_of "$dest.part")"
  if [ "$got" != "$want" ]; then
    rm -f "$dest.part"
    die "sha256 mismatch for $url (want $want, got $got)"
  fi
  mv "$dest.part" "$dest"
}

# Version of the app, read from src/xtractor/__init__.py without importing it.
app_version() {
  sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' "$REPO_ROOT/src/xtractor/__init__.py" | head -1
}
