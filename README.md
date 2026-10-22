# Xtractor

Command-line tool that extracts the audio (`-a`) or video (`-v`) track from a YouTube video.
It ships as a single self-contained binary for Apple Silicon Macs (arm64) with ffmpeg and a
JavaScript runtime bundled, so nothing else needs to be installed.

## Legal notice

> Legal notice: YouTube's Terms of Service restrict downloading content without permission. Use Xtractor only for content you have the right to download (your own uploads, Creative Commons or public-domain material, content with the owner's permission, or lawful personal archival). Xtractor does not and will not circumvent DRM; DRM-protected streams are refused.

## Install

Xtractor v1 is built for **macOS on Apple Silicon (arm64)** only.

### Homebrew (recommended)

```sh
brew install OWNER/xtractor/xtractor
brew upgrade xtractor        # later, to update
```

Homebrew downloads are not quarantined, so the binary runs immediately.

### Direct download

Download `Xtractor-<version>-macos-arm64.tar.gz` and `SHA256SUMS` from the
[releases page](https://github.com/OWNER/Xtractor/releases), then verify and install:

```sh
curl -LO https://github.com/OWNER/Xtractor/releases/download/vX.Y.Z/Xtractor-X.Y.Z-macos-arm64.tar.gz
curl -LO https://github.com/OWNER/Xtractor/releases/download/vX.Y.Z/SHA256SUMS
shasum -a 256 -c SHA256SUMS --ignore-missing
tar -xzf Xtractor-X.Y.Z-macos-arm64.tar.gz
install -m 755 Xtractor /usr/local/bin/Xtractor
```

The binary is ad-hoc signed, not notarized by Apple (no Developer ID). How macOS treats it
depends on how you downloaded it:

- Downloaded with `curl` (or `wget`, or installed by Homebrew): no quarantine attribute is set
  and it runs normally.
- Downloaded in a **browser**: macOS marks the file as quarantined and Gatekeeper blocks it
  ("cannot be opened because the developer cannot be verified"). Remove the mark once:

  ```sh
  xattr -d com.apple.quarantine /usr/local/bin/Xtractor
  ```

  (or right-click the file in Finder, choose Open, and confirm).

Details of the signing and Gatekeeper behaviour are in [docs/BUILD_NOTES.md](docs/BUILD_NOTES.md).

### From source (developers)

```sh
pipx install .        # needs Python >= 3.10, plus ffmpeg and deno (or node) on your PATH
```

## Usage

```sh
Xtractor -a https://youtu.be/VIDEOID                 # audio, m4a, 44.1 kHz
Xtractor -a --sample-rate 48000 --audio-format wav https://youtu.be/VIDEOID
Xtractor -v --resolution 720 -o ~/Movies https://youtu.be/VIDEOID
Xtractor -a -q -o out/ https://youtu.be/VIDEOID      # scripting: only the saved path on stdout
```

Exactly one of `-a` / `-v` is required (except for `--list-formats`, `--self-update`,
`--version` and `-h`). Progress goes to stderr; the saved file path is the only line on stdout,
so `file=$(Xtractor -a URL)` works. Only single videos are supported: a `watch?v=X&list=Y`
URL downloads video X; playlist and channel URLs are rejected.

### Defaults and why

- **Audio: 44.1 kHz, M4A (AAC-LC).** YouTube serves AAC at 44.1 kHz, so the default path
  stream-copies it: no re-encoding, no resampling, no quality loss, and it is fast and plays
  everywhere. If only a 48 kHz stream exists, Xtractor transcodes and says so.
- **48 kHz** is the alternative for video and DAW work (`--sample-rate 48000`). Opus always
  runs at 48 kHz. Rates above 48 kHz are accepted but only upsample the (at most 48 kHz)
  source, and a warning says so.
- **Formats:** `m4a` (default), `mp3` (most compatible, always a transcode), `opus` (best
  quality per bit), `flac` and `wav` (lossless containers; the source is still lossy).
  Lossy transcodes use 128k unless you pass `--audio-quality`.
- **Video: 1080p MP4 (H.264 + AAC)**, which plays on every device. Above 1080p, YouTube only
  offers VP9/AV1, so the container switches to MKV (announced on stderr) unless you pass
  `--strict-format`, which fails with exit 6 instead.

### Options

| Option | Meaning | Default |
|---|---|---|
| `-a`, `--audio` | Extract audio only | |
| `-v`, `--video` | Download video (with audio) | |
| `--sample-rate HZ` | 22050, 32000, 44100, 48000, 88200 or 96000 (audio only) | 44100; 48000 for opus |
| `--audio-format FMT` | `m4a`, `mp3`, `opus`, `flac`, `wav` | `m4a` |
| `--audio-quality BR` | Bitrate for lossy formats, e.g. `192k` | 128k when transcoding; m4a is copied if untouched |
| `--resolution RES` | `360`, `480`, `720`, `1080`, `1440`, `2160`, `best` | `1080` |
| `--video-format FMT` | `mp4`, `mkv`, `webm` | `mp4` |
| `--strict-format` | Fail instead of switching container/codec | off |
| `-o`, `--output PATH` | Output directory, or full file path | current directory |
| `-n`, `--name TEMPLATE` | Filename template; fields: title, id, uploader, upload_date, resolution | `%(title)s` |
| `--overwrite` | Replace an existing file | skip, print its path, exit 0 |
| `-q`, `--quiet` | Errors only | |
| `--verbose` | Debug detail including underlying tool commands | |
| `--list-formats` | Show available streams for the URL and exit | |
| `--no-playlist` | Accepted no-op: single-video handling is already the default | |
| `--self-update` | Update the Xtractor binary from the latest GitHub release and exit | |
| `--version` | Print version and exit | |
| `-h`, `--help` | Show help and exit | |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (or skipped because the file already exists) |
| 1 | Unexpected or internal error |
| 2 | Usage error / invalid arguments |
| 3 | Video unavailable (private, removed, blocked, DRM, live) |
| 4 | Network error after retries |
| 5 | Missing dependency (ffmpeg or JavaScript runtime) |
| 6 | Requested format/resolution cannot be satisfied (`--strict-format`) |
| 7 | File system error (permissions, disk full) |
| 130 | Interrupted (Ctrl-C / SIGTERM) |

## Updating

- Homebrew: `brew upgrade xtractor`.
- Standalone binary: `Xtractor --self-update`. It asks the GitHub releases API for the latest
  release, downloads the tarball and `SHA256SUMS`, verifies the SHA-256, ad-hoc re-signs the
  new binary, checks that it runs and swaps it in atomically. The previous binary is kept as
  `Xtractor.bak` and restored if anything fails. It contacts GitHub only when you run it.
  Exit 4 means GitHub was unreachable, 1 a checksum or archive problem (nothing was changed),
  7 that the install directory is not writable. Set `XTRACTOR_UPDATE_REPO=owner/repo` to
  update from a different repository.
- Source installs: `pipx upgrade Xtractor` (`--self-update` prints this hint).

## Troubleshooting

- **"Sign in to confirm you're not a bot", "Unable to extract", or other extraction errors**:
  YouTube changes often. Run `Xtractor --self-update` (or `brew upgrade xtractor` /
  `pipx upgrade Xtractor`) to get the newest yt-dlp.
- **JavaScript runtime errors (exit 5)**: the binary bundles one. In a source install, install
  `deno` (or `node`) and make sure it is on your `PATH`.
- **Missing or corrupt bundled tools (exit 5)**: the bundled ffmpeg and runtime are unpacked on
  first run into `~/Library/Caches/Xtractor/`. Delete that directory and run again. A `ffmpeg`
  on your `PATH` is preferred over the bundled one, and may be swapped for your own build.
- **Blocked by Gatekeeper after a browser download**: see [Direct download](#direct-download).
- **Format fallbacks**: if the requested resolution does not exist, the next lower one is used;
  above 1080p with `mp4` the container becomes `mkv`; a missing 44.1 kHz AAC stream triggers a
  transcode. Each is announced on stderr. Use `--list-formats` to see what is available and
  `--strict-format` to turn container/codec switches into an error.
- **File exists**: the existing path is printed and the run exits 0; use `--overwrite` to
  replace it.

## Build from source

The release binary is built on an Apple Silicon Mac by `scripts/build_binary.sh`
(PyInstaller, a minimal LGPL ffmpeg and a JavaScript runtime), which writes
`dist/Xtractor`, `dist/Xtractor-<version>-macos-arm64.tar.gz` and `dist/SHA256SUMS`. See
[docs/BUILD_NOTES.md](docs/BUILD_NOTES.md) for prerequisites and details. Tagging `vX.Y.Z`
runs `.github/workflows/release.yml`, which builds and publishes the GitHub release; a weekly
`live.yml` job runs the live tests against the latest yt-dlp and opens an issue on failure.

## Development

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy --strict src
pytest                          # unit tests; no network, ffmpeg tests skip if ffmpeg is absent
XTRACTOR_LIVE=1 pytest -m live  # opt-in tests against real YouTube
```

Design documents: [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) and
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md). Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE). Bundled components (ffmpeg under the LGPL, yt-dlp, the JavaScript
runtime) are covered by `THIRD_PARTY_NOTICES` shipped in each release tarball.
