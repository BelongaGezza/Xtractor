# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Core features (version 0.1.0, not yet released): audio extraction (`-a`: m4a, mp3, opus,
  flac, wav, stream copy where possible), video download (`-v`: mp4, mkv, webm up to 2160p and
  `best`), `--list-formats`, filename templates, atomic writes and clean Ctrl-C handling, and a
  single self-contained arm64 macOS binary with bundled ffmpeg and JavaScript runtime.
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
- Videos with several audio tracks (auto-dubbing) now use the original-language track instead
  of an arbitrary dub, for audio and video output; plain streams are preferred over DRC in
  both. Equal video streams prefer DASH over HLS.
- `--version` prints the bundled yt-dlp, ffmpeg and JavaScript runtime versions (from build
  metadata, no subprocess).
- Tool precedence is documented and consistent: bundled first, `XTRACTOR_USE_SYSTEM_TOOLS=1`
  prefers `PATH` (spec, README and `-h` agree). `deno`/`node` on `PATH` are version-checked.
- `-o` is validated before the network probe (exit 2 for a file in the way, exit 7 for an
  unwritable directory); a directory at the target path is exit 7 instead of a silent skip.
- Update hints name `Xtractor --self-update` in the binary and `pipx upgrade Xtractor` for
  source installs; the bot check has its own message (exit 3); the error classifier no longer
  mistakes unrelated text for a missing JavaScript runtime, and HTTP 403 is treated as a stale
  extractor.
- `--self-update` rejects any other argument.
- Progress: a tiny first stream no longer silences later ones in non-TTY mode, and errors
  after a TTY progress line start on a new line.
- Security: yt-dlp plugin auto-loading is disabled; control, bidi and invisible characters are
  stripped from filenames and escaped on the terminal; a trailing newline in a video ID
  (`%0A`) is rejected; SIGHUP cleans up like Ctrl-C.
- Audio extraction no longer prefers YouTube's dynamic-range-compressed `-drc` variants; plain
  `140` is stream-copied at 44.1 kHz again.
- The YouTube JS challenge is solved once per run instead of twice (`-a`: 9.2 s to 4.9 s with
  quickjs-ng, 4.5 s to 2.4 s with deno).
- Single-file binary start-up: `-h` 1.47 s to 0.45 s and `--version` 0.86 s to 0.38 s warm
  (lazy imports in the CLI, 12 fewer unpacked extension modules); the 0.5 s budget is met.

### Changed
- F8 is documented honestly: retries resume within a run; an interrupted run starts over.
- Specification v0.3. F11 (config file) and F12 (completions) are deferred beyond v1.
- The README marks the install section as pending: no release has been published yet.
- `-h` mode heading now lists the modes that need no `-a`/`-v`.
