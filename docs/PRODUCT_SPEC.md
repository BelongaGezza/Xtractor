# Xtractor — Product Specification

Version: 0.3 · Date: 2026-10-23 · Status: Ready for development (packaging spike pending)

**Changelog**
- v0.3 (2026-10-23): review follow-up. Tool precedence is now bundled first with `XTRACTOR_USE_SYSTEM_TOOLS=1` to prefer `$PATH` (replaces "PATH ffmpeg preferred"); original-language audio track rule for dubbed videos (3.4); F8 resume is within a run only; F11 (config file) and F12 (completions) are deferred beyond v1; `-o` is validated before any network call; `--version` prints bundled tool versions from build metadata; `--self-update` accepts no other arguments; mp3 is limited to 48 kHz; the packaged ffmpeg is ffmpeg only (no ffprobe) with a few extra decoders/filters (BUILD_NOTES).
- v0.2 (2026-10-22): folded in plan resolutions S1–S14 (docs/DEVELOPMENT_PLAN.md section 0); removed the lowercase `xtractor` alias; added exit 130 and redefined exit 5; deliverable is now a single self-contained arm64 macOS binary with embedded minimal LGPL ffmpeg and a bundled JS runtime (reverses OQ2); added `--self-update` and the distribution plan (section 9).
- v0.1 (2026-10-22): initial draft.

## 1. Purpose

`Xtractor` is a command-line tool that takes a YouTube video URL and saves either its audio track (`-a`) or its video (`-v`) to a local file. It aims to be simple, predictable and scriptable: one URL in, one file out, sensible defaults, every knob reachable from the command line.

### Intended use and legal note
YouTube's Terms of Service restrict downloading content without permission. Xtractor is intended for content the user has the right to download (their own uploads, Creative Commons / public-domain material, content with the owner's permission, personal archival where lawful). The tool must show a short notice in `-h` and README stating this. It must not include any DRM circumvention, and must refuse DRM-protected streams.

### Non-goals (v1)
- GUI, web service, or browser extension
- Non-YouTube sites (the architecture should not preclude them later)
- Playlist/channel bulk download (v1 downloads only the single video of a `watch?v=…&list=…` URL and rejects bare playlist/channel URLs with exit 2; see CLI rule 6)
- Intel macOS, Linux and Windows binaries (the v1 deliverable is arm64 macOS only)
- Editing, trimming, subtitles, thumbnails (candidates for v2)
- Circumventing DRM, paywalls, age/region gates, or authentication

## 2. Users and key scenarios

| User | Scenario |
|---|---|
| Podcaster / researcher | `Xtractor -a <url>` to get a listenable audio file for a talk or lecture |
| Musician / editor | `Xtractor -a --sample-rate 48000 --audio-format wav <url>` for a DAW at 48 kHz |
| Archivist | `Xtractor -v --resolution 1080 <url>` for a compatible MP4 |
| Scripter | `Xtractor -a -q -o out/ <url>` in a batch job; non-zero exit codes on failure |

## 3. Research findings (basis for defaults)

### 3.1 Audio sample rates
| Rate | Where it is the standard |
|---|---|
| 22.05 / 24 kHz | Low-bandwidth speech, legacy |
| 32 kHz | Broadcast, some speech codecs |
| **44.1 kHz** | CD audio and most music distribution; AAC/MP3 default |
| **48 kHz** | Professional video/film and DAW work; Opus always operates at 48 kHz internally |
| 88.2 / 96 kHz | High-resolution studio audio (no benefit when the source is YouTube) |

What YouTube actually serves (as exposed by yt-dlp):
- AAC-LC in MP4/M4A, ~128 kbps, typically **44.1 kHz** (itag 140), sometimes 48 kHz
- Opus in WebM, ~50–160 kbps, **48 kHz** (itags 249/250/251)
- Source audio is lossy, so output above 48 kHz or "lossless" output adds no real fidelity.

**Default: 44,100 Hz, M4A (AAC-LC).** Rationale: it matches the native stream, so the default path can stream-copy without re-encoding or resampling (no quality loss, fastest), it is the music/consumer standard, and M4A plays everywhere.
**Copy rule (S2):** the selector prefers an AAC stream whose sample rate equals the target. Stream-copy happens only when the source rate equals the target and no `--audio-quality` was given. If no such stream exists (YouTube sometimes serves only 48 kHz AAC), Xtractor transcodes to AAC with resampling and says so on stderr; this is a notice, not an error.
**Alternates via `--sample-rate`:** 22050, 32000, 44100, 48000, 88200, 96000. Rates above 48000 are accepted for `m4a`, `flac` and `wav` (opus is fixed at 48000) but print a warning that the source is ≤48 kHz and the result is upsampled; `mp3` is limited to 48000 (88200 and 96000 are a usage error, exit 2, because MP3 does not define those rates). Any other value is rejected with the list of valid values.

### 3.2 Audio formats
| `--audio-format` | Codec | Notes |
|---|---|---|
| `m4a` (default) | AAC-LC | Native YouTube stream; copy when no rate/bitrate override |
| `mp3` | MP3 (libmp3lame) | Maximum compatibility; always a transcode |
| `opus` | Opus in .opus/Ogg | Best quality per bit; native 48 kHz. The resolved rate is 48000; an explicit `--sample-rate` other than 48000 is a usage error (exit 2) |
| `flac` | FLAC | Lossless container for editing; file is large but source is still lossy — warn once |
| `wav` | PCM 16-bit | For DAWs; large files |

`--audio-quality` takes a bitrate matching `^\d{2,3}k$` for lossy targets (e.g. `192k`, `256k`, `320k`). It has **no parser default** (S1): when omitted, lossy transcodes use 128k and m4a may be stream-copied; an explicit value on m4a forces a transcode. It is ignored with a notice for flac/wav.

**Sample-rate resolution (S3, closes OQ3):** `--sample-rate` has no parser default; the resolved rate is 44100, except opus which is 48000.

### 3.3 Video formats
YouTube serves video and audio separately above 360p (DASH), so a download means fetch best video-only + best audio-only and mux with ffmpeg.
- **H.264 (avc1) + AAC in MP4**: tops out at 1080p, plays on every OS/device/editor. 
- **VP9 / AV1 in WebM (or MKV)**: needed for 1440p, 4K, 8K; smaller files; poorer hardware/editor support.

**Default: MP4 container, H.264 video + AAC audio, best available up to 1080p.** Rationale: universal compatibility, stream-copy mux (no re-encode, fast, lossless relative to source).
**Alternates:**
- `--video-format mp4|mkv|webm` (default `mp4`)
- `--resolution` `360|480|720|1080|1440|2160|best` (default `1080`). If the requested height is unavailable in the chosen format, pick the highest below it and say so. Requesting >1080 (or `best` when the best is >1080) with `mp4` auto-selects the best available codec (VP9/AV1) and switches the container to `mkv` (announced on stderr) unless `--strict-format` is given, in which case it fails with exit 6. Because this depends on the available streams, the decision is made after probing, not at argument time (S10).
- `webm` (S11) is restricted to VP9/AV1 video + Opus audio. If no such stream exists at or below the height, `--strict-format` gives exit 6; otherwise the container falls back to `mkv` with an announcement.
- `--codec` is out of scope for v1; codec follows the format/resolution rules above.
- Ties between otherwise equal video streams prefer progressive DASH over HLS (m3u8).

### 3.4 Audio track selection (multi-language videos)
Many videos carry several audio tracks (auto-dubbing). Xtractor always selects the **original-language** track: among audio-only streams it keeps those with the highest yt-dlp `language_preference` (YouTube marks the original 10 and dubs -1) or, lacking that, a format note containing "original" / "(default)"; only then does it rank by bitrate/codec. Non-DRC (plain) streams beat DRC variants. The same rule applies to the audio muxed into `-v` output. There is no option to choose another language in v1.

## 4. Command-line interface

Executable name: **`Xtractor`** (exact case), the only one shipped (S4). On the default case-insensitive APFS, `xtractor` already resolves to it; Linux users can define a shell alias. No lowercase alias is packaged because it would overwrite the real script on case-insensitive filesystems.

```
Usage: Xtractor [OPTIONS] URL

Extract the audio or video track from a YouTube video.

Mode (exactly one required, except for --list-formats / --self-update / --version / -h):
  -a, --audio              Extract audio only
  -v, --video              Download video (with audio)

Audio options (with -a):
      --sample-rate HZ     22050|32000|44100|48000|88200|96000  [default: 44100; 48000 for opus]
      --audio-format FMT   m4a|mp3|opus|flac|wav               [default: m4a]
      --audio-quality BR   Bitrate for lossy formats, e.g. 192k [default: 128k for transcoded
                           lossy output; m4a is stream-copied when omitted]

Video options (with -v):
      --resolution RES     360|480|720|1080|1440|2160|best     [default: 1080]
      --video-format FMT   mp4|mkv|webm                        [default: mp4]
      --strict-format      Fail instead of switching container/codec

General:
  -o, --output PATH        Output directory, or full file path [default: current dir]
  -n, --name TEMPLATE      Filename template [default: "%(title)s"]
      --overwrite          Replace existing file (default: skip, print its path, exit 0)
  -q, --quiet              Errors only
      --verbose            Debug detail including underlying tool commands (not with -q)
      --list-formats       Show available streams for URL (table on stdout) and exit
      --no-playlist        Accepted no-op: single-video handling is already the default
      --self-update        Update the Xtractor binary from the latest GitHub release and exit
      --version            Print Xtractor, yt-dlp and bundled ffmpeg/JS runtime versions and exit
  -h, --help               Show this help and exit

Exit codes: 0 ok, 1 internal, 2 usage, 3 unavailable, 4 network, 5 bundled tool missing,
            6 format unsatisfiable, 7 filesystem, 130 interrupted.

Examples:
  Xtractor -a https://youtu.be/VIDEOID
  Xtractor -a --sample-rate 48000 --audio-format wav https://youtu.be/VIDEOID
  Xtractor -v --resolution 720 -o ~/Movies https://youtu.be/VIDEOID
```

### CLI rules
1. `-h`/`--help` prints the above (accurate to the implemented options, auto-generated from the parser so it cannot drift), exit 0, works with no network and no ffmpeg present.
2. Exactly one of `-a` / `-v` for download mode. Neither or both → usage error, exit 2. `--list-formats` (S7) is an informational mode: it needs only a URL, requires no mode flag, prints its table to stdout, produces no file, needs no ffmpeg and exits 0. `--self-update`, `--version` and `-h` likewise need no mode or URL. `--self-update` accepts no other argument (exit 2).
3. Audio options with `-v` (or video options with `-a`) → usage error naming the offending flag.
4. URL validation: accept `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`, `m.youtube.com`, `music.youtube.com`, `youtube.com/live/`. Reject non-YouTube hosts and malformed URLs before any network call. Strip tracking params.
5. Output path (S6, validated before any network call): `-o` is a directory if it exists as one, ends in a path separator, or has no extension; otherwise it is a full file path. A file path's extension must match the chosen format, else exit 2. `-o` as a file path combined with `-n` is exit 2. Filenames are sanitised for macOS/Linux/Windows (control, bidi and other invisible characters are removed). A `-o` directory path that is (or lies below) a regular file is a usage error (exit 2); a directory that cannot be written is exit 7; a directory sitting at the final target path is exit 7, never a "skipped" file. Titles and other untrusted text are escaped before they are written to the terminal.
6. Playlist (S14): a URL with `watch?v=X&list=Y` downloads only video X. `playlist?list=`, `/channel/…` and `/@handle` URLs exit 2 ("playlists are not supported in v1"). Both are pure URL-parse decisions made before any network call. `--no-playlist` is an accepted no-op.
7. Progress: a single-line progress bar (percent, size, speed, ETA) on a TTY; plain periodic lines otherwise; nothing with `-q`. In download mode, progress goes to stderr and the final saved path is the **only** line on stdout so output can be piped (`$(Xtractor -a URL)`). If the file already exists and `--overwrite` is not given (S5), the existing path is still printed to stdout, "exists, skipping" goes to stderr, exit 0.
8. `-q` together with `--verbose` is a usage error, exit 2 (S9).
9. Metadata (S13): best effort via ffmpeg `-metadata` (title, artist, date, comment/purl = source URL). WAV gets INFO tags where ffmpeg supports them. Missing tag support never fails the run.

### Exit codes
| Code | Meaning |
|---|---|
| 0 | Success (or skipped because file exists) |
| 1 | Unexpected/internal error |
| 2 | Usage error / invalid arguments |
| 3 | Video unavailable (private, removed, region/age-blocked, DRM, live-not-ended) |
| 4 | Network error after retries |
| 5 | Bundled or located dependency missing or corrupt (embedded/`$PATH` ffmpeg or ffprobe, JS runtime) and could not be (re)extracted |
| 6 | Requested format/resolution cannot be satisfied (with `--strict-format`, or no stream at all satisfies webm/height rules) |
| 7 | File system error (permissions, disk full) |
| 130 | Interrupted (Ctrl-C / SIGTERM, S8); no partial files remain |

## 5. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| F1 | `-a` saves audio in the selected format at the selected sample rate | Must |
| F2 | `-v` saves a muxed video+audio file at the selected resolution/container | Must |
| F3 | Default audio path uses stream-copy when no transformation is requested | Must |
| F4 | `-h` lists all options, defaults and examples | Must |
| F5 | Validate arguments up front, fail fast with actionable messages | Must |
| F6 | Embed metadata (title, artist/channel, date, source URL) in audio files where the container supports it; embed in video MP4/MKV | Should |
| F7 | `--list-formats` | Should |
| F8 | Retry transient network failures (3 retries, exponential backoff); a dropped connection resumes the partial download **within the same run**. An interrupted or failed run starts over (F9/F10 take priority: no partial files remain) | Should |
| F9 | Write to a temp file and atomically rename on success; clean up on failure/Ctrl-C | Must |
| F10 | Clean Ctrl-C handling (exit 130, no partial files left) | Must |
| F11 | Config file (`~/.config/xtractor/config.toml`) for default overrides; CLI wins | Could, **deferred (not in v1)** |
| F12 | Shell completions (zsh/bash) | Could, **deferred (not in v1)** |
| F13 | `--self-update`: replace the binary with the latest GitHub release after verifying its SHA-256 | Should |
| F14 | Single self-contained arm64 macOS binary with embedded ffmpeg and JS runtime (section 6, 9) | Must |

## 6. Non-functional requirements

- **Platforms:** the v1 deliverable is **macOS on Apple Silicon (arm64) only**. Intel Macs, Linux and Windows are out of scope for the binary; the Python source remains portable and installable with `pipx` for developers.
- **Build, don't rebuild:** use the maintained open-source **yt-dlp** for stream extraction (YouTube changes its delivery frequently; reimplementing extraction is not viable) and **ffmpeg** for muxing/transcoding/resampling. Xtractor is the opinionated, simple front end with the defaults and validation above.
- **Single self-contained binary (reverses OQ2):** the deliverable is one arm64 Mach-O executable built with **PyInstaller `--onefile`** (Nuitka is the alternative if the spike shows unacceptable startup or size). It embeds Python, yt-dlp (`yt-dlp[default]`, which brings the `yt-dlp-ejs` component that PyPI yt-dlp otherwise lacks), a **minimal LGPL ffmpeg** (the `ffmpeg` executable only; no ffprobe) and a **JS runtime**.
  - *ffmpeg:* custom build without `--enable-gpl` / `--enable-nonfree`; encoders/decoders limited to aac, libmp3lame, libopus, flac, pcm; muxers limited to mp4, matroska, webm, ogg, wav (plus matching demuxers/protocols needed for local files). Embedded in the binary and extracted on first run to `~/Library/Caches/Xtractor/<version>-<sha8>/`, verified by hash on each start. **Tool precedence:** the embedded ffmpeg and JS runtime are used first, for reproducible behaviour with a known-good build; setting `XTRACTOR_USE_SYSTEM_TOOLS=1` makes Xtractor prefer `ffmpeg` and a JS runtime from `$PATH` (falling back to the embedded copies). Outside a bundled build (pipx install) only `$PATH` is used. A deno or node runtime found on `$PATH` must be deno >= 2.3 / node >= 22, else exit 5 with the required version. The build enables a few more decoders/encoders/filters than the minimal list above (vorbis, alac, webp, png, mjpeg, loudnorm, mpegts; see docs/BUILD_NOTES.md). LGPL obligations (licence text, source offer, replaceability through `XTRACTOR_USE_SYSTEM_TOOLS=1`) are documented in the README.
  - *JS runtime:* since 2025.11.12 yt-dlp needs an external JavaScript runtime to solve YouTube challenges. Supported: deno >= 2.3 (default/recommended), node >= 22, quickjs/quickjs-ng (slow, can take minutes, and unsandboxed), bun (deprecated). The runtime is a **build parameter** (`JS_RUNTIME=deno|quickjs-ng`): **deno preferred, quickjs-ng fallback**, final choice decided by the packaging spike (docs/SPIKE_PACKAGING.md) on size, speed and signing behaviour. It is embedded and extracted to the same cache directory and passed to yt-dlp explicitly; a user-installed runtime on `$PATH` is not required and is only used with `XTRACTOR_USE_SYSTEM_TOOLS=1` (or in a source install).
- **Dependency handling:** locate/extract ffmpeg and the JS runtime at the start of download operations (not for `-h`/`--version`/`--list-formats` where not needed); if missing or corrupt and re-extraction fails, print an actionable message and exit 5. yt-dlp is updated by releasing a new Xtractor build (and `--self-update`); extraction failures that look like stale-extractor issues suggest running `Xtractor --self-update` (S12; for source installs `pipx upgrade Xtractor`); the hint text depends on whether Xtractor runs as the frozen binary. YouTube's "confirm you're not a bot" challenge exits 3 with its own message and the same update hint.
- **Language / packaging:** Python >=3.10 (3.12 for the binary), `pyproject.toml` (hatchling, src layout), single console-script `Xtractor`, dependency `yt-dlp[default]>=<release current at implementation time>` with no upper cap (S12); CI keeps a lock for reproducibility plus a scheduled "latest yt-dlp" job.
- **Startup and size budgets (targets, to be confirmed by the spike):** `Xtractor -h` and `--version` cold start <= 1.5 s, warm <= 0.5 s on an M-series Mac (the `--onefile` unpack cost; fall back to `--onedir`-inside-tarball or Nuitka if exceeded); binary <= 120 MB with deno (<= 70 MB with quickjs-ng).
- **Performance:** no added overhead beyond the underlying download; default audio path involves no re-encode.
- **Security:** never shell out with unsanitised strings (argument lists only); no credentials or cookies handled in v1; no telemetry; yt-dlp plugin auto-loading is disabled (no third-party code is imported from user config dirs, the executable directory or `sys.path`); the `--self-update` checksum is fetched from the same release over HTTPS, so it detects corruption and tampering in transit but is not a signature. The only network access besides YouTube is `--self-update`, which contacts GitHub releases only when the user runs it, over HTTPS, and verifies a SHA-256 checksum before replacing the binary.
- **Testing:** unit tests for argument validation, URL parsing, format selection logic, filename sanitising; integration tests with yt-dlp/ffmpeg mocked; a small opt-in live smoke test against a public-domain / Creative Commons video, excluded from default CI.
- **Quality bar:** type-checked, linted, ≥85% line coverage on non-I/O logic; `README` with install, usage and troubleshooting.

## 7. Acceptance criteria (abridged)

1. `Xtractor -h` exits 0 and lists every option in section 4 with its default.
2. `Xtractor <url>` (no mode) and `Xtractor -a -v <url>` exit 2 with a usage message.
3. `Xtractor -a <url>` produces a playable `.m4a`, 44.1 kHz, verified by `ffprobe`, without re-encoding when the source is 44.1 kHz AAC.
4. `Xtractor -a --sample-rate 48000 --audio-format wav <url>` produces a 48 kHz PCM WAV.
5. `Xtractor -a --sample-rate 12345 <url>` exits 2 listing valid rates.
6. `Xtractor -v <url>` produces an H.264/AAC MP4 ≤1080p that plays in QuickTime.
7. `Xtractor -v --resolution 2160 <url>` yields a ≤2160p MKV/WebM (VP9/AV1) and announces the container switch; with `--strict-format` and `--video-format mp4` exits 6.
8. Private/removed video → exit 3 with a human-readable reason; no partial files remain.
9. stdout contains only the output path on success.
10. Ctrl-C mid-download leaves no temp/partial files.

11. `Xtractor --self-update` on a build older than the latest release replaces the binary atomically after SHA-256 verification; a checksum mismatch aborts with the old binary intact; `Xtractor --version` then shows the new version.
12. On a clean arm64 Mac with no Homebrew, Python, ffmpeg or Node/deno installed, `Xtractor -a <url>` succeeds (first run extracts tools to `~/Library/Caches/Xtractor/`), and the notarized (or ad-hoc signed) binary launches without Gatekeeper blocking when installed via `curl` or Homebrew.

## 8. Decisions and open questions
Resolved:
- OQ1 Distribution: GitHub release tarball + Homebrew tap (section 9); PyPI optional.
- OQ2 Bundle ffmpeg: **yes** (minimal LGPL build, embedded and used first; `XTRACTOR_USE_SYSTEM_TOOLS=1` prefers `$PATH`). Reverses v0.1.
- OQ3 Sample-rate default: global 44100, opus 48000 (S3).
- OQ4 Windows/Linux: out of scope for the binary; source remains portable, not CI-gated.

Pending:
- **P1 (decided 2026-10-22):** ad-hoc signing for v1; no Apple Developer ID. Notarization is deferred and can be added later without design changes (see 9).
- **P2 (spike):** JS runtime = deno vs quickjs-ng; `--onefile` vs Nuitka vs `--onedir` based on measured startup/size (docs/SPIKE_PACKAGING.md).

## 9. Distribution
1. **Primary:** a GitHub release containing `Xtractor-<version>-macos-arm64.tar.gz` (the binary, LICENSE, THIRD_PARTY_NOTICES with ffmpeg LGPL source offer) and `SHA256SUMS`. The binary is signed with a Developer ID Application certificate with hardened runtime and **notarized** (stapling is not possible for a bare Mach-O; staple is applied only if shipped in a pkg/dmg, otherwise Gatekeeper checks the ticket online). Requires an Apple Developer ID, US$99/yr — **a user decision (P1)**.
2. **Homebrew tap** (`<owner>/homebrew-xtractor`): formula downloads the release tarball, verifies the sha256, installs `Xtractor`. `brew upgrade` is the update path for brew users (`--self-update` detects a Homebrew-managed path and refuses, pointing to `brew upgrade`; exit 2).
3. **No-cost fallback:** ad-hoc signing (`codesign -s -`), which is the minimum for arm64 binaries to run at all. Users must clear quarantine or approve via System Settings (Privacy & Security); documented in the README.
4. **Gatekeeper/quarantine behaviour:** files downloaded with a browser get the `com.apple.quarantine` attribute, so an un-notarized binary is blocked ("cannot be opened because the developer cannot be verified") and needs `xattr -d com.apple.quarantine` or manual approval; a notarized one opens. Files fetched with `curl`/`wget`, or installed by Homebrew, are not quarantined and run even when only ad-hoc signed. `--self-update` downloads via the tool itself (no quarantine attribute) and verifies the checksum.
5. **`--self-update`:** queries the latest release via the GitHub releases API, compares versions, downloads the tarball and `SHA256SUMS`, verifies the SHA-256, extracts to a temp file beside the running binary, re-applies no quarantine, and atomically replaces it (`os.replace`). Network failure: exit 4; checksum mismatch or corrupt archive: exit 1, old binary untouched; non-writable install location: exit 7. "Already up to date" exits 0. Prints the new version to stdout.
