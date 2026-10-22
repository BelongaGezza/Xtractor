#!/usr/bin/env bash
# Fill version, sha256 and repository into the Homebrew formula.
# Usage: update_formula.sh VERSION TARBALL [FORMULA] [OWNER/REPO]
#   VERSION   e.g. 1.0.0 (no leading v)
#   TARBALL   the Xtractor-<VERSION>-macos-arm64.tar.gz file (its sha256 is computed)
#   FORMULA   formula to rewrite in place (default: packaging/homebrew/xtractor.rb)
#   OWNER/REPO GitHub repository hosting the release (default: keep what the formula has)
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
  echo "usage: $0 VERSION TARBALL [FORMULA] [OWNER/REPO]" >&2
  exit 2
fi
version="${1#v}"
tarball="$2"
here="$(cd "$(dirname "$0")" && pwd)"
formula="${3:-$here/xtractor.rb}"
repo="${4:-}"

[ -f "$tarball" ] || { echo "tarball not found: $tarball" >&2; exit 1; }
[ -f "$formula" ] || { echo "formula not found: $formula" >&2; exit 1; }
case "$version" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "invalid version: $version" >&2; exit 2 ;;
esac

sha="$(shasum -a 256 "$tarball" | awk '{print $1}')"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed -E \
  -e "s|^  version \".*\"|  version \"$version\"|" \
  -e "s|^  sha256 \".*\"|  sha256 \"$sha\"|" \
  "$formula" > "$tmp"
if [ -n "$repo" ]; then
  sed -E -i.bak "s#github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#github.com/$repo#g" "$tmp"
  rm -f "$tmp.bak"
fi
cat "$tmp" > "$formula"
echo "updated $formula: version $version sha256 $sha"
