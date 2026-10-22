# Xtractor — Product Specification

Version: 0.1 (draft) · Date: 2026-10-22 · Status: Ready for development planning

## 1. Purpose

`Xtractor` is a command-line tool that takes a YouTube video URL and saves either its audio track (`-a`) or its video (`-v`) to a local file. It aims to be simple, predictable and scriptable: one URL in, one file out, sensible defaults, every knob reachable from the command line.

### Intended use and legal note
YouTube's Terms of Service restrict downloading content without permission. Xtractor is intended for content the user has the right to download (their own uploads, Creative Commons / public-domain material, content with the owner's permission, personal archival where lawful). The tool must show a short notice in `-h` and README stating this. It must not include any DRM circumvention, and must refuse DRM-protected streams.

### Non-goals (v1)
- GUI, web service, or browser extension
- Non-YouTube sites (the architecture should not preclude them later)
- Playlist/channel bulk download (v1 rejects playlist URLs with a clear message unless `--no-playlist` semantics apply; see 5.6)
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
**Alternates via `--sample-rate`:** 22050, 32000, 44100, 48000, 88200, 96000. Rates above 48000 are accepted but print a warning that the source is ≤48 kHz and the result is upsampled. Any other value is rejected with the list of valid values.

### 3.2 Audio formats
| `--audio-format` | Codec | Notes |
|---|---|---|
| `m4a` (default) | AAC-LC | Native YouTube stream; copy when no rate/bitrate override |
| `mp3` | MP3 (libmp3lame) | Maximum compatibility; always a transcode |
| `opus` | Opus in .opus/Ogg | Best quality per bit; native 48 kHz, so `--sample-rate` is fixed to 48000 (other values error) |
| `flac` | FLAC | Lossless container for editing; file is large but source is still lossy — warn once |
| `wav` | PCM 16-bit | For DAWs; large files |

`--audio-quality` takes a bitrate for lossy targets (`128k` default, `192k`, `256k`, `320k`). It is ignored with a notice for flac/wav.

### 3.3 Video formats
YouTube serves video and audio separately above 360p (DASH), so a download means fetch best video-only + best audio-only and mux with ffmpeg.
- **H.264 (avc1) + AAC in MP4**: tops out at 1080p, plays on every OS/device/editor. 
- **VP9 / AV1 in WebM (or MKV)**: needed for 1440p, 4K, 8K; smaller files; poorer hardware/editor support.

**Default: MP4 container, H.264 video + AAC audio, best available up to 1080p.** Rationale: universal compatibility, stream-copy mux (no re-encode, fast, lossless relative to source).
**Alternates:**
- `--video-format mp4|mkv|webm` (default `mp4`)
- `--resolution` `360|480|720|1080|1440|2160|best` (default `1080`). If the requested height is unavailable in the chosen format, pick the highest below it and say so. Requesting >1080 with `mp4` auto-selects the best available codec (VP9/AV1) and switches the container to `mkv` (announced on stderr) unless `--strict-format` is given, in which case it fails.
- `--codec` is out of scope for v1; codec follows the format/resolution rules above.

## 4. Command-line interface

Executable name: **`Xtractor`** (exact case). Also installable under alias `xtractor` on case-sensitive systems.

```
Usage: Xtractor [OPTIONS] URL

Extract the audio or video track from a YouTube video.

Mode (exactly one required):
  -a, --audio              Extract audio only
  -v, --video              Download video (with audio)

Audio options (with -a):
      --sample-rate HZ     22050|32000|44100|48000|88200|96000  [default: 44100]
      --audio-format FMT   m4a|mp3|opus|flac|wav               [default: m4a]
      --audio-quality BR   Bitrate for lossy formats, e.g. 192k [default: 128k]

Video options (with -v):
      --resolution RES     360|480|720|1080|1440|2160|best     [default: 1080]
      --video-format FMT   mp4|mkv|webm                        [default: mp4]
      --strict-format      Fail instead of switching container/codec

General:
  -o, --output PATH        Output directory, or full file path [default: current dir]
  -n, --name TEMPLATE      Filename template [default: "%(title)s"]
      --overwrite          Replace existing file (default: skip and exit 0 with notice)
  -q, --quiet              Errors only
      --verbose            Debug detail including underlying tool commands
      --list-formats       Show available streams for URL and exit
      --no-playlist        Treat URL with list= parameter as the single video (default behaviour)
      --version            Print version and exit
  -h, --help               Show this help and exit

Examples:
  Xtractor -a https://youtu.be/VIDEOID
  Xtractor -a --sample-rate 48000 --audio-format wav https://youtu.be/VIDEOID
  Xtractor -v --resolution 720 -o ~/Movies https://youtu.be/VIDEOID
```

### CLI rules
1. `-h`/`--help` prints the above (accurate to the implemented options, auto-generated from the parser so it cannot drift), exit 0, works with no network and no ffmpeg present.
2. Exactly one of `-a` / `-v`. Neither or both → usage error, exit 2.
3. Audio options with `-v` (or video options with `-a`) → usage error naming the offending flag.
4. URL validation: accept `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`, `m.youtube.com`, `music.youtube.com`, `youtube.com/live/`. Reject non-YouTube hosts and malformed URLs before any network call. Strip tracking params.
5. Output path: a directory or a file path; the extension is derived from the format (a conflicting user extension is an error). Filenames are sanitised for macOS/Linux/Windows.
6. Playlist: a URL containing `list=` downloads only the single video identified by `v=`. A bare playlist URL (no video) exits 2 with "playlists are not supported in v1".
7. Progress: a single-line progress bar (percent, size, speed, ETA) on a TTY; plain periodic lines otherwise; nothing with `-q`. Progress goes to stderr; the final saved path is the **only** line printed to stdout so output can be piped (`$(Xtractor -a URL)`).

### Exit codes
| Code | Meaning |
|---|---|
| 0 | Success (or skipped because file exists) |
| 1 | Unexpected/internal error |
| 2 | Usage error / invalid arguments |
| 3 | Video unavailable (private, removed, region/age-blocked, DRM, live-not-ended) |
| 4 | Network error after retries |
| 5 | Missing dependency (ffmpeg) |
| 6 | Requested format/resolution cannot be satisfied (with `--strict-format`) |
| 7 | File system error (permissions, disk full) |

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
| F8 | Retry transient network failures (3 attempts, exponential backoff) and resume partial downloads | Should |
| F9 | Write to a temp file and atomically rename on success; clean up on failure/Ctrl-C | Must |
| F10 | Clean Ctrl-C handling (exit 130, no partial files left) | Must |
| F11 | Config file (`~/.config/xtractor/config.toml`) for default overrides; CLI wins | Could |
| F12 | Shell completions (zsh/bash) | Could |

## 6. Non-functional requirements

- **Platforms:** macOS (primary, Apple Silicon + Intel), Linux; Windows best-effort.
- **Build, don't rebuild:** use the maintained open-source **yt-dlp** for stream extraction (YouTube changes its delivery frequently; reimplementing extraction is not viable) and **ffmpeg** for muxing/transcoding/resampling. Xtractor is the opinionated, simple front end with the defaults and validation above.
- **Dependency handling:** detect ffmpeg at startup of download operations (not for `-h`/`--version`); on absence print a platform-specific install hint (`brew install ffmpeg`) and exit 5. yt-dlp is a pinned Python dependency with a documented upgrade path; extraction failures that look like stale-extractor issues suggest updating it.
- **Language / packaging (recommendation, engineer to confirm in plan):** Python ≥3.10, `pyproject.toml`, console-script entry point `Xtractor`, installable via `pipx install .`; consider Homebrew formula later.
- **Performance:** no added overhead beyond the underlying download; default audio path involves no re-encode.
- **Security:** never shell out with unsanitised strings (argument lists only); no credentials or cookies handled in v1; no telemetry.
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

## 8. Open questions (to resolve in the plan, defaults noted)
1. Distribution: pipx from git only for v1 (default) vs. PyPI/Homebrew.
2. Bundle ffmpeg or require it installed (default: require installed).
3. Whether `--sample-rate` should default per format (e.g. 48 kHz for opus/wav) — default: single global default 44100, except opus fixed at 48000.
4. Windows support level (default: best-effort, not CI-gated).
