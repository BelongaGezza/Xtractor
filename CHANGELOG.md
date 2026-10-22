# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `Xtractor --self-update`: checks the latest GitHub release, verifies the tarball against
  `SHA256SUMS`, ad-hoc re-signs and atomically replaces the binary, keeping `Xtractor.bak` and
  rolling back on failure. Refuses Homebrew-managed installs (use `brew upgrade`) and prints a
  `pipx upgrade Xtractor` hint for source installs. `XTRACTOR_UPDATE_REPO` selects the repository.
- Release workflow (tag `v*` on macos-14) publishing the arm64 tarball and `SHA256SUMS`, with a
  dry-run build for packaging pull requests.
- Weekly live-test workflow against the latest yt-dlp that opens an issue on failure.
- Homebrew formula template and `packaging/homebrew/update_formula.sh`.
- README with install, usage, option table, exit codes and troubleshooting.

### Fixed
- Audio extraction no longer prefers YouTube's dynamic-range-compressed `-drc` variants; plain
  `140` is stream-copied at 44.1 kHz again.
- The YouTube JS challenge is solved once per run instead of twice (`-a`: 9.2 s to 4.9 s with
  quickjs-ng, 4.5 s to 2.4 s with deno).
- Single-file binary start-up: `-h` 1.47 s to 0.45 s and `--version` 0.86 s to 0.38 s warm
  (lazy imports in the CLI, 12 fewer unpacked extension modules); the 0.5 s budget is met.

### Changed
- `-h` mode heading now lists the modes that need no `-a`/`-v`.
