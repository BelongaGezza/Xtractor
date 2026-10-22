# Xtractor — Development Plan

Based on `docs/PRODUCT_SPEC.md` v0.1. Date: 2026-10-22.
Requirement references: `F1..F12` and `NFR` (spec sections 5 and 6), `AC1..AC10` (section 7), `CLI-1..CLI-7` (the "CLI rules" in section 4), `OQ1..OQ4` (section 8).

Local tooling check (this machine): python3 is **3.9.6**, `ffmpeg`, `yt-dlp` and `yt_dlp` are **not installed**. Consequence: the dev environment must be bootstrapped (`brew install python@3.12 ffmpeg`), and 3.9 cannot be used (the spec already requires >=3.10, and current yt-dlp releases dropped 3.9).

---

## 0. Spec issues found and proposed resolutions

| # | Issue | Proposed resolution |
|---|---|---|
| S1 | Default `--audio-quality 128k` plus "stream-copy when no transformation is requested" (F3) conflict if 128k is treated as an explicit value for m4a. | `--audio-quality` has no parser default (internal `None`); help shows "[default: 128k for transcoded lossy output]". An explicit value on m4a forces a transcode; `None` allows copy. |
| S2 | AC3 assumes 44.1 kHz AAC source, but YouTube sometimes serves 48 kHz AAC, and AAC can't be both copied and resampled. | Selector prefers `m4a` with `asr == target`. If none exists, transcode to AAC with `-ar` and say so on stderr (not an error). Copy only when `asr == target` and no quality override. |
| S3 | `--sample-rate` default is 44100 but opus is "fixed to 48000 (other values error)". A bare `--audio-format opus` would then error against the default. | Parser default is `None`. Resolved rate = 44100, except opus = 48000 (closes OQ3). Explicit non-48000 with opus is exit 2. Explicit 48000 is fine. |
| S4 | `xtractor` lowercase alias collides with `Xtractor` on case-insensitive filesystems (default APFS): pip would overwrite one script with the other. | Ship exactly one console script, `Xtractor`. Document that on case-insensitive macOS `xtractor` already works; Linux users can `alias`. Drop the alias from packaging. |
| S5 | "Skip existing file, exit 0": unclear what goes to stdout. | Print the existing path to stdout (so `$(Xtractor ...)` still works) plus "exists, skipping" on stderr. |
| S6 | `-o` as a full file path together with `-n` is undefined. | Both given and `-o` is a file path: exit 2. A file path's extension must match the format (CLI-5) or exit 2. `-o` is treated as a directory if it exists as one, ends in a separator, or has no extension. |
| S7 | `--list-formats` conflicts with "only the saved path on stdout" (CLI-7) and with "exactly one of -a/-v" (CLI-2). | `--list-formats` is an informational mode: table to stdout, mode flag not required, no file is produced. CLI-7 applies to download mode. |
| S8 | Exit code for Ctrl-C (130) is in F10 but not in the exit-code table. | Add 130 to the table in the README and help epilog. |
| S9 | `--no-playlist` is listed as an option but is already the default behaviour, and `-q` + `--verbose` is undefined. | Keep `--no-playlist` as an accepted no-op for yt-dlp-muscle-memory. `-q` with `--verbose` is exit 2. |
| S10 | `--resolution best` with `mp4`: "best" may be >1080 so the container switch happens after probing, not at argument time. | Container resolution is a pure function of (probed formats, request); the announcement happens at selection time, after probe. `--strict-format` exit 6 is raised from the same function. |
| S11 | `--video-format webm` only works with VP9/AV1 + Opus; the spec doesn't say what happens when the requested height only has H.264. | webm restricts to VP9/AV1 video + Opus audio. If none at or below the height: strict gives exit 6; otherwise fall back to mkv with an announcement (same pattern as mp4). |
| S12 | "yt-dlp is a **pinned** dependency" vs "suggest updating it when extraction breaks" and rapid YouTube churn. | Declare `yt-dlp>=<release current at implementation time>` (no upper cap) in `pyproject.toml`; CI keeps a lock for reproducibility plus a scheduled "latest yt-dlp" job. Upgrade path: `pipx upgrade Xtractor` / `pipx inject --force Xtractor yt-dlp -U`. |
| S13 | Metadata (F6) for WAV/FLAC: tag support differs; "date, source URL" has no standard m4a/opus tag. | Best effort via ffmpeg `-metadata` (title, artist, date, comment=URL; `purl`/`comment` for URL). WAV gets INFO chunk where ffmpeg supports it; missing tags never fail the run. |
| S14 | Error for a bare playlist URL says "exit 2" but URL validation (CLI-4) says "before any network call"; a `watch?v=X&list=Y` URL is valid. | Both are pure URL parse decisions (no network). `playlist?list=` and `/channel/`, `/@handle` give exit 2. |

---

## 1. Tech stack (confirmed) and rationale

| Decision | Choice | Rationale / deviation |
|---|---|---|
| Language | **Python >=3.10** (develop and CI on 3.12; CI matrix 3.10, 3.12, 3.13) | yt-dlp is a Python library; in-process use gives structured errors, hooks and format metadata. No deviation from spec. |
| Packaging | `pyproject.toml`, **src layout**, backend **hatchling**, console script `Xtractor` (single, see S4) | Standard, pipx-friendly. |
| CLI parsing | **`argparse`** (stdlib) | Zero extra deps; `-h` is generated from the parser (CLI-1/F4, AC1). Custom `ArgumentParser.error` -> exit 2. Click/Typer rejected: heavier, and their help formatting is harder to pin to the spec layout. |
| Extraction/download | **yt-dlp as a library** (`yt_dlp.YoutubeDL`), not subprocess | Typed exceptions, progress hooks, explicit format dicts, no string parsing. |
| Muxing/transcode | **ffmpeg / ffprobe on PATH** (OQ2: **require installed, do not bundle**) | Bundling: licensing (GPL builds), size, per-arch wheels. We detect and give `brew install ffmpeg`/apt/winget hints, exit 5. |
| Subprocess | `subprocess.run([...list...], shell=False)` only | NFR security. |
| Distribution (OQ1) | v1: **`pipx install git+https://...`** and `pipx install .`; PyPI publish prepared (name availability checked) but optional at 1.0; Homebrew formula post-1.0 | Matches spec default; keeps the legal notice/up-keep burden low initially. |
| Windows (OQ4) | Best-effort, **not CI-gated**; path sanitising and `ffmpeg.exe` lookup kept portable; one optional manual smoke run before release | Matches spec default. |
| Sample-rate default (OQ3) | Global 44100; opus 48000 (S3) | Matches spec default. |
| Tooling | `pytest`, `pytest-cov`, `ruff` (lint+format), `mypy --strict` (on `src/`), `pre-commit`, GitHub Actions | NFR "type-checked, linted, >=85% coverage". |
| Runtime deps | `yt-dlp` only. Dev: pytest, pytest-cov, mypy, ruff. | Minimal surface. |
| Config (F11), completions (F12) | Deferred to M9 (Could). Config via stdlib `tomllib` (3.11+) with `tomli` fallback for 3.10. Completions are static scripts generated at release. | Keeps v1 core small. |

---

## 2. Architecture

### 2.1 Package layout

```
Xtractor/
  pyproject.toml  README.md  LICENSE  .github/workflows/{ci,live,release}.yml
  docs/
  src/xtractor/
    __init__.py        # __version__
    __main__.py        # python -m xtractor -> cli.main
    cli.py             # build_parser(), parse_args() -> Options, main(argv) -> int
    options.py         # frozen dataclasses AudioOptions/VideoOptions/Options, validation, defaults resolution
    urls.py            # parse_youtube_url(str) -> VideoRef(video_id, canonical_url); raises UsageError
    errors.py          # XtractorError hierarchy with .exit_code; classify_exception()
    formats.py         # PURE: select_audio(), select_video(), Plan dataclasses (no I/O)
    ytdlp.py           # adapter: Extractor Protocol + YtDlpExtractor (probe, download)
    ffmpeg.py          # locate_ffmpeg(), build_audio_argv(), run_ffmpeg(), ffprobe helpers
    paths.py           # sanitise(), resolve_output(), template expansion, temp dir, atomic_move()
    pipeline.py        # run(options, deps) -> Path : orchestrates probe->select->download->post->move
    ui.py              # Reporter: info/warn/error to stderr, -q/--verbose, progress rendering (TTY vs plain)
    config.py          # (M9) load defaults
  tests/
    unit/ integration/ live/   fixtures/info_*.json (recorded yt-dlp info dicts, trimmed)
```

Dependency direction: `cli -> pipeline -> {formats, ytdlp, ffmpeg, paths, ui}`; `formats`, `urls`, `options`, `errors` import nothing from I/O modules. This keeps the >=85% coverage target (NFR) meaningful on logic modules.

### 2.2 Key interfaces

```python
# options.py
@dataclass(frozen=True)
class Options:
    mode: Literal["audio", "video"]; url: VideoRef
    output: Path | None; name_template: str; overwrite: bool
    quiet: bool; verbose: bool; list_formats: bool
    audio: AudioOptions | None; video: VideoOptions | None
@dataclass(frozen=True)
class AudioOptions:  sample_rate: int; fmt: AudioFmt; bitrate: str | None   # resolved per S1, S3
@dataclass(frozen=True)
class VideoOptions:  max_height: int | None; fmt: Literal["mp4","mkv","webm"]; strict: bool  # None = best

# formats.py (pure)
@dataclass(frozen=True)
class AudioPlan:  format_id: str; copy: bool; ext: str; ffmpeg_codec_args: list[str]; notices: list[str]
@dataclass(frozen=True)
class VideoPlan:  format_selector: str; container: str; notices: list[str]   # selector like "137+140"
def select_audio(formats: Sequence[FormatInfo], opts: AudioOptions) -> AudioPlan
def select_video(formats: Sequence[FormatInfo], opts: VideoOptions) -> VideoPlan   # may raise FormatUnavailable (exit 6)

# ytdlp.py
class Extractor(Protocol):
    def probe(self, ref: VideoRef) -> MediaInfo: ...                  # metadata + formats, no download
    def download(self, ref, format_selector: str, dest_dir: Path, outtmpl: str,
                 merge_to: str | None, on_progress: Callable[[Progress], None]) -> Path: ...
# ffmpeg.py
def locate_ffmpeg() -> Path          # shutil.which; raises MissingDependency(exit 5)
def build_audio_argv(src: Path, dst: Path, plan: AudioPlan, opts: AudioOptions, meta: Tags) -> list[str]
def run_ffmpeg(argv: list[str], *, verbose: bool) -> None   # stdout=DEVNULL, stderr captured, -nostdin -loglevel error
```

`pipeline.run` takes a `Deps` bundle (extractor, ffmpeg runner, reporter, clock/tmp factory) so integration tests inject fakes.

### 2.3 Data flow

1. `cli.main`: parse -> resolve defaults (S1/S3) -> validate cross-flag rules (CLI-2, CLI-3, CLI-5 pre-checks, S6, S9) -> `urls.parse_youtube_url` (CLI-4, CLI-6, no network). Any failure: exit 2 before touching network or ffmpeg. `-h`/`--version` return before ffmpeg lookup (NFR).
2. For download/list modes: `locate_ffmpeg()` (exit 5 with hint). `--list-formats` needs no ffmpeg; skip the check there.
3. `extractor.probe(ref)` -> `MediaInfo` (title, uploader, upload_date, id, `live_status`, formats with `format_id, ext, vcodec, acodec, height, fps, asr, abr, tbr, has_drm`). Reject: `is_live`/`is_upcoming`, or all candidate formats `has_drm` -> exit 3.
4. `formats.select_*` -> plan (+ user-facing notices, e.g. container switch, height fallback, upsample warning, flac lossy-source warning).
5. Resolve final path (`paths.resolve_output`): sanitised template, extension from plan. Exists and not `--overwrite`: print path to stdout, exit 0 (S5).
6. Create temp dir **inside the output directory** (`.Xtractor-<rand>/`, same filesystem so rename is atomic). Download there. Audio: ffmpeg step writes `final.tmp.<ext>`. Video: yt-dlp merges (`merge_output_format`).
7. `atomic_move` (`os.replace`) to final path; remove temp dir in `finally` (also on KeyboardInterrupt/SIGTERM). `print(final_path)` on stdout, once, as the last action.

### 2.4 yt-dlp usage

Two-phase: `probe` with `download=False`, our own pure selection, then download by explicit `format_id` (e.g. `"137+140"`). Rationale: unit-testable selection with recorded info dicts, exact control of strict/fallback announcements, and no dependence on yt-dlp's selector-string semantics changing.

Base `YoutubeDL` params (all set in one function `base_params()`):
```
quiet=True, no_warnings=True, noprogress=True, logger=StderrLogger, noplaylist=True,
retries=3, fragment_retries=3, extractor_retries=3, socket_timeout=30,
retry_sleep_functions={"http": exp, "fragment": exp, "extractor": exp},  # exp(n)=min(2**n, 30)
continuedl=True, nopart=False, overwrites=False, windowsfilenames=True,
paths={"home": tmp, "temp": tmp}, outtmpl="%(id)s.%(ext)s",   # our own naming; final name applied by paths.py
progress_hooks=[...], ffmpeg_location=str(ffmpeg_dir), color="never"
```
No cookies, no credentials, no `--extractor-args` hacks, no DRM options (F: legal). `allow_unplayable_formats` is never set.

Metadata (F6): audio via ffmpeg `-metadata title= artist= date= comment=<url>`; video via yt-dlp postprocessor `{"key": "FFmpegMetadata", "add_metadata": True}`. Thumbnails/subtitles/chapters: not requested.

**Audio selection** (`select_audio`), candidates = formats with `vcodec == "none"` and no DRM:
- m4a target: prefer `ext == m4a` (AAC) with `asr == rate`; then any m4a (transcode+`-ar`); then any best audio (transcode).
- opus target: prefer Opus (`acodec` starts with `opus`, itag 251) -> remux to `.opus`; copy only if rate is 48000 and no bitrate override; otherwise `libopus -b:a`.
- mp3/flac/wav: best audio by `abr` (prefer Opus 251 or m4a 140, whichever has higher `abr`), always decode.

ffmpeg argv shapes (built as lists; `-nostdin -hide_banner -loglevel error -y` first, `-vn -map 0:a:0 -map_metadata -1` plus tags):
| Target | Condition | Codec args |
|---|---|---|
| m4a | source AAC, `asr==rate`, no bitrate override (**default path, F3/AC3**) | `-c:a copy -movflags +faststart` |
| m4a | otherwise | `-c:a aac -b:a {br or 128k} -ar {rate}` |
| mp3 | always | `-c:a libmp3lame -b:a {br or 128k} -ar {rate}` |
| opus | source Opus, 48 kHz, no override | `-c:a copy` (to `.opus`/Ogg) |
| opus | otherwise | `-c:a libopus -b:a {br or 128k} -ar 48000` |
| flac | always | `-c:a flac -ar {rate}` (bitrate ignored: notice; one-time lossy-source warning) |
| wav | always | `-c:a pcm_s16le -ar {rate}` (bitrate ignored: notice) |
Rates >48000: warn "source <=48 kHz, upsampled". Resampling uses ffmpeg's default swresample (no extra filter in v1).

**Video selection** (`select_video`), `R` = requested max height (`best` = unbounded), candidates video-only + audio-only (progressive 360p `18` only as last resort):
1. Container `mp4` and `R<=1080` (or best which is <=1080): video = highest `height<=R` with `vcodec^=avc1`, ties by `fps`, then `tbr`; audio = best `ext==m4a` (AAC). Equivalent selector: `bv[vcodec^=avc1][height<=R]+ba[ext=m4a]`. Mux with `merge_output_format=mp4` (stream copy, no re-encode).
2. Requested height absent: pick the next lower and notice "720p unavailable for mp4/H.264, using 480p".
3. `R>1080` (or best >1080) with `mp4`: if strict -> `FormatUnavailable` exit 6. Else choose best across all codecs by `height<=R`, tie `vp9` > `av1` > `avc1` by availability/compat, audio best Opus/AAC, container `mkv`; notice "container switched mp4 -> mkv (VP9/AV1 required for >1080p)". Matches AC7.
4. `mkv` requested: best by height <= R, prefer avc1 when `R<=1080`, otherwise per rule 3; any audio (copy into mkv).
5. `webm` requested: VP9/AV1 + Opus only (S11); fallback mkv or exit 6 if strict.
6. If nothing satisfies even the minimum (no format <= R): strict exit 6; otherwise use the lowest available and notice.

### 2.5 Error -> exit code mapping (`errors.classify_exception`)

| Condition | Class | Exit |
|---|---|---|
| argparse error, validation, bad URL, bare playlist, conflicting flags | `UsageError` | 2 |
| yt-dlp `DownloadError` / `ExtractorError(expected=True)` with Private / removed / unavailable / age / region / members / "Sign in to confirm" / copyright; `is_live`/`is_upcoming`; `has_drm` | `VideoUnavailable` (human reason from the message, with the video ID) | 3 |
| `TransportError`, `URLError`, `socket.timeout`, `ConnectionError`, `ContentTooShortError`, HTTP 5xx/429 after retries | `NetworkError` | 4 |
| ffmpeg/ffprobe not found (`which`, `FileNotFoundError`) | `MissingDependency` | 5 |
| `FormatUnavailable` (strict mode only) | `FormatUnavailable` | 6 |
| `OSError` with EACCES, EPERM, ENOSPC, EROFS, EDQUOT, ENAMETOOLONG on our paths | `FileSystemError` | 7 |
| `KeyboardInterrupt`, SIGTERM (handler raises) | cleanup then | 130 (143 mapped to 130 is acceptable; document) |
| non-expected `ExtractorError` ("Unable to extract..."), ffmpeg non-zero, anything else | `InternalError` | 1; message adds "try updating yt-dlp: pipx upgrade Xtractor" for extractor failures; `--verbose` prints traceback |

Rules: all exceptions are caught once at the top of `main`; one-line `Xtractor: error: <message>` to stderr; no stack trace unless `--verbose`. Classification is a pure function over exception type/message and is table-tested with recorded messages.

### 2.6 stdout / stderr discipline
- Exactly one `print(path)` in the whole code base (`pipeline`/`cli`), at the end of success (or skip). A CI grep/test asserts no other `print(` without `file=`.
- Reporter writes to `sys.stderr`; yt-dlp gets a `logger` object routed to Reporter (debug only at `--verbose`); ffmpeg runs with `stdout=DEVNULL`, `stderr=PIPE`; its stderr is shown only on failure or `--verbose`. `--verbose` also logs the ffmpeg argv (shell-quoted via `shlex.join`).
- Progress: TTY -> single carriage-return line (percent, size, speed, ETA); non-TTY -> a line per ~10% / 5 s; `-q` -> nothing; errors always shown.
- `--list-formats` writes its table to stdout (S7).

---

## 3. Work breakdown

Size: S <= half day, M ~1 day, L 2-3 days. Order is the dependency order; tasks in the same milestone with no listed dependency can be parallel.

### M0 — Scaffold and tooling
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T0.1 | Dev env bootstrap doc + `pyproject.toml` (hatchling, src layout, entry point `Xtractor`, `requires-python>=3.10`, yt-dlp dep), `.gitignore`, LICENSE | `pipx install .` gives `Xtractor --version` | S | — | NFR, OQ1 |
| T0.2 | ruff, mypy strict, pytest+cov config, pre-commit | `ruff check`, `mypy src`, `pytest` all run green on skeleton | S | T0.1 | NFR quality bar |
| T0.3 | GitHub Actions `ci.yml`: matrix py3.10/3.12/3.13 on ubuntu + macOS, installs ffmpeg, lint/type/test/coverage gate (85% on non-I/O modules) | CI green on PR | S | T0.2 | NFR |

### M1 — CLI surface and validation (no network)
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T1.1 | `errors.py`: exception hierarchy with exit codes; `main()` top-level handler | Unit: each class maps to its exit code | S | T0.1 | exit codes table, F5 |
| T1.2 | `cli.build_parser`: all options from spec section 4 in the spec's grouped layout, epilog with examples, exit-code table and legal notice | `-h` exits 0 with no ffmpeg/network; test asserts every option string and default appears (AC1) | M | T1.1 | F4, AC1, CLI-1, legal |
| T1.3 | `options.py` validation: exactly one mode, cross-mode flags name the offender, sample-rate allow-list message, opus rate rule, bitrate regex (`^\d{2,3}k$`), `-q`/`--verbose`, flac/wav quality ignored notice, defaults resolution (S1, S3) | Unit table covers AC2, AC5; exit 2; message names the flag and lists valid values | M | T1.2 | F5, CLI-2/3, AC2, AC5, S1, S3, S9 |
| T1.4 | `urls.py`: accepted hosts/paths (CLI-4), strip tracking params (`si`, `utm_*`, `feature`, `pp`, `t`, `index`, `list`), `list=` handling, bare playlist/channel -> exit 2 | Parametrised table of >=30 URLs (valid/invalid/malformed, no network) | M | T1.1 | CLI-4, CLI-6, S14 |
| T1.5 | `--version`, ffmpeg check hook (only on download/list modes) | `Xtractor --version` works without ffmpeg; download w/o ffmpeg -> exit 5 with brew hint | S | T1.2 | NFR deps, exit 5 |

### M2 — Paths and filesystem safety
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T2.1 | `paths.sanitise` (strip `/ \ : * ? " < > |`, control chars, trailing dots/spaces, Windows reserved names, collapse whitespace, 200-byte cap preserving extension) | Unit incl. unicode, emoji, empty title -> video id | S | T0.1 | CLI-5 |
| T2.2 | `resolve_output`: dir vs file path (S6), template expansion with a restricted field set (`title, id, uploader, upload_date, resolution`), ext derivation, conflicting-extension error | Unit with tmp_path; AC-level behaviours | M | T2.1, T1.3 | CLI-5, `-n`, `-o` |
| T2.3 | Temp dir in output dir, `atomic_move`, cleanup context manager, signal handlers (SIGINT/SIGTERM) | Test: exception mid-run leaves no `.Xtractor-*` dir; existing file is preserved on failure; skip-vs-overwrite logic (S5) | M | T2.2 | F9, F10, AC8, AC10 |

### M3 — Format selection (pure logic)
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T3.1 | `FormatInfo`/`MediaInfo` models + fixtures (record real info dicts once from yt-dlp, trim to relevant keys; plus hand-made edge cases) | Fixtures: 44.1k-AAC, 48k-AAC-only, Opus-only, no-avc1, 4K VP9/AV1, 720p max, DRM, live | S | T0.1 | NFR testing |
| T3.2 | `select_audio` per 2.4 table | Unit per row: copy on 44.1k AAC (AC3), transcode with `-ar` on 48k->44.1k, wav 48k (AC4), opus fixed 48k, mp3 | M | T3.1, T1.3 | F1, F3, AC3, AC4 |
| T3.3 | `select_video` rules 1-6 incl. notices and strict exit 6 | Unit: AC6 (avc1<=1080 mp4), AC7 (2160 -> mkv + notice; strict -> `FormatUnavailable`), height fallback, webm, mkv | L | T3.1 | F2, AC6, AC7 |
| T3.4 | `build_audio_argv` (+ unit tests asserting exact argv lists) | Snapshot of argv for all table rows; contains no shell strings | S | T3.2 | F1, F3, NFR security |

### M4 — yt-dlp adapter and audio end-to-end
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T4.1 | `ytdlp.py`: `base_params`, `probe` -> `MediaInfo`, error translation via `classify_exception` | Mocked `YoutubeDL`: expected-error messages map to 3/4/1 (table test) | M | T1.1, T3.1 | exit codes, F5 |
| T4.2 | `Extractor.download` (format_id, paths, progress hooks, retries/backoff params, resume) | Mock asserts params (`retries=3`, `noplaylist`, `continuedl`, backoff fn growth) | M | T4.1 | F8 |
| T4.3 | `pipeline.run` for audio: probe -> select -> download -> ffmpeg -> metadata -> atomic move -> print | Integration with fake extractor and real/fake ffmpeg; stdout is exactly one path (AC9) | L | T2.3, T3.4, T4.2, T1.5 | F1, F3, F6, F9, AC3, AC4, AC9 |
| T4.4 | `ffmpeg.run_ffmpeg` + ffprobe verification helper for tests (codec, `sample_rate`, tags) | Real-ffmpeg tests (skipped without ffmpeg): lavfi sine -> AAC m4a 44.1k copy; -> wav 48k | M | T3.4 | AC3, AC4 |

### M5 — Video end-to-end
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T5.1 | Video branch of `pipeline.run`: selector `"vid+aud"`, `merge_output_format`, FFmpegMetadata PP, container switch notice | Fake extractor test asserts selected ids, container, notice text on stderr | M | T3.3, T4.3 | F2, F6, AC6, AC7 |
| T5.2 | `--list-formats` (table: id, ext, res, fps, codecs, rate, size, notes; stdout) | Snapshot test over fixtures; exit 0 without ffmpeg | S | T4.1 | F7, S7 |
| T5.3 | DRM / live / upcoming rejection | Fixtures -> exit 3, message states reason; nothing written | S | T4.1 | exit 3, legal |

### M6 — Robustness and UX
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T6.1 | `ui.Reporter` + progress rendering (TTY/non-TTY/quiet) | Unit with fake streams (isatty True/False); no stdout writes | M | T4.2 | CLI-7, `-q`, `--verbose` |
| T6.2 | Ctrl-C/SIGTERM: cleanup, exit 130; failure paths leave no partial files | Test: raise `KeyboardInterrupt` from fake extractor mid-download -> exit 130, directory empty (except pre-existing files) | M | T2.3, T4.3 | F10, AC10, AC8 |
| T6.3 | Retry/backoff verification and network error mapping (exit 4); disk-full/permission simulation (exit 7) | Tests with injected `OSError(ENOSPC)` / `TransportError` | M | T4.2 | F8, exit 4/7 |
| T6.4 | Stale-extractor hint + `--verbose` traceback + ffmpeg argv logging | Test asserts hint text for "Unable to extract" | S | T4.1 | NFR dependency handling |

### M7 — Docs, legal, polish
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T7.1 | README: install (pipx, ffmpeg per OS), usage, defaults rationale (sample rates/formats from spec section 3), exit codes (incl. 130), troubleshooting (update yt-dlp, ffmpeg missing, format fallbacks), **legal notice** | Reviewed against `-h`; legal text identical in README and `-h` epilog | M | T1.2 | legal, NFR |
| T7.2 | Print notice test: `-h` contains the notice; no DRM-related options exist | Test greps `-h` output | S | T1.2 | legal |

### M8 — Release hardening
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T8.1 | Opt-in live smoke test (`pytest -m live`, env `XTRACTOR_LIVE=1`) against a CC/public-domain video (pin the URL in `tests/live/urls.py`; verify license at pick time) | Runs AC3, AC4, AC6, AC7 for real with `ffprobe` assertions; excluded from default CI | M | M5 | AC3-AC7 |
| T8.2 | Scheduled (weekly) `live.yml` workflow with latest yt-dlp, failure opens an issue | Workflow runs manually via dispatch | S | T8.1 | S12, risk R1 |
| T8.3 | Manual acceptance run of AC1-AC10 on macOS arm64 (+ Intel if available) and Ubuntu; QuickTime playback check for AC6 | Checklist completed in release PR | M | M7, T8.1 | AC1-AC10 |
| T8.4 | Release: version bump, tag, build sdist/wheel (`python -m build`), `pipx install` from wheel + git URL test in a clean venv | Clean-env install works; `Xtractor --version` matches tag | S | T8.3 | OQ1 |

### M9 — Optional (Could)
| ID | Task | Acceptance | Size | Deps | Satisfies |
|---|---|---|---|---|---|
| T9.1 | `config.py`: `~/.config/xtractor/config.toml` (XDG-aware), keys mirror long options; CLI overrides; unknown key -> warning | Precedence tests (default < config < CLI) | M | M1 | F11 |
| T9.2 | zsh/bash completion scripts generated from the parser, shipped in repo `completions/` | Scripts source without error; flags match parser | S | T1.2 | F12 |

Critical path: T0.1 -> T1.x -> T3.x -> T4.3 -> T5.1 -> T6.2 -> T8.x. M2 and M3 can proceed in parallel after M1.

---

## 4. Test strategy

**Layers**
1. **Unit (default CI, no network, no ffmpeg needed)**: `urls`, `options`, `formats`, `paths`, `errors.classify_exception`, `build_audio_argv`, `ui` rendering. Target >=85% line coverage on these (enforced with `--cov-fail-under=85` on those modules; I/O modules `ytdlp.py`, `ffmpeg.run_*` excluded from the gate but still tested).
2. **Mocked integration (default CI)**: `pipeline.run` with `FakeExtractor` (serves recorded info dicts; "downloads" by writing a small file made with real ffmpeg lavfi, or a stub) and a `FakeFfmpeg` that records argv and writes the output file. Plus `CliRunner`-style tests calling `main(argv)` with `capsys` to assert stdout/stderr/exit code.
3. **Real-ffmpeg tests (marker `ffmpeg`, skipped when absent; CI installs ffmpeg)**: generate a sine source with `ffmpeg -f lavfi -i sine=frequency=440:sample_rate=44100 -c:a aac` and check, via ffprobe, that the default path yields the same stream (`codec_name=aac`, `sample_rate=44100`) and that packet data is copied (compare stream md5 with `-f md5` of source vs. output); the 48 kHz wav case yields `pcm_s16le`/48000; opus 48000; mp3 `-ar`.
4. **Live smoke (marker `live`, opt-in `XTRACTOR_LIVE=1`, never in default CI; weekly scheduled workflow)** against one short CC/public-domain video.

**Concrete cases**
- CLI: no mode (AC2), both modes (AC2), `-a --resolution 720` names `--resolution`, `-v --sample-rate 48000` names `--sample-rate`, `--sample-rate 12345` lists valid rates (AC5), `--sample-rate 96000` accepted with warning, `--audio-format opus --sample-rate 44100` exit 2, `--audio-format opus` alone resolves to 48000, `--audio-quality 192` (no `k`) exit 2, `-q --verbose` exit 2, `-o file.mp3` with `--audio-format m4a` exit 2, `-o x.m4a -n foo` exit 2, `--version`/`-h` with PATH lacking ffmpeg exit 0.
- URLs: valid: `watch?v=`, `youtu.be/ID?t=10`, `/shorts/`, `m.`, `music.`, `/live/`, `watch?v=ID&list=PL..&index=3` (strip `list`/`index`/`si`/`utm_*` from canonical URL; `list=` retained only as information); invalid: `vimeo.com`, `youtube.com.evil.com`, `https://youtube.com/watch` (no v), `playlist?list=`, `javascript:`, empty, bad ID length, non-http schemes.
- Formats: each table row of 2.4 plus: 48 kHz-only AAC with default rate -> transcode + notice; Opus-only video source with `--audio-format m4a` -> AAC transcode; 4K video with `mp4` -> mkv + notice (AC7); with `--strict-format` -> exit 6; requested 1440 when max is 1080 -> uses 1080 with notice; no avc1 at all with mp4 non-strict -> fallback; webm requests; `best`.
- Pipeline: success prints exactly one stdout line equal to the final path (AC9); existing file skip exits 0 and prints path (S5); `--overwrite` replaces atomically; exception mid-download leaves directory identical (AC8/AC10); `KeyboardInterrupt` -> 130 (AC10); filename sanitising of `a/b:c?.mp3`; progress never on stdout.
- Errors: parametrised recorded yt-dlp messages ("Private video", "Video unavailable", "This video is not available in your country", "Sign in to confirm your age", "Sign in to confirm you're not a bot", "Unable to extract ...", `HTTPError 503`, `TransportError`) -> expected exit codes; `OSError(ENOSPC)` -> 7; missing ffmpeg -> 5 with `brew install ffmpeg` hint on macOS.
- Security: an assertion test that `subprocess.run` is never invoked with `shell=True` or a `str` argv (monkeypatch spy), plus a hostile title (`"; rm -rf ~ #"`) produces a sanitised name and an argv element, not shell text.
- Static gate: a test scans `src/` for `print(` calls lacking `file=` other than the single allowed site.

---

## 5. Risks and mitigations

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **yt-dlp breakage** from YouTube changes (frequent, sometimes within days) | High / High | Floor-only version spec (S12); weekly live workflow with latest yt-dlp opens an issue; README upgrade command; stale-extractor hint on non-expected extractor errors; all yt-dlp use confined to `ytdlp.py` so API drift has one fix site; probe-then-select relies only on stable info-dict keys (`format_id, ext, vcodec, acodec, height, asr, abr, tbr, has_drm`) and fixture tests detect key changes. |
| R2 | **ffmpeg absent or too old/stripped build** (no libmp3lame/libopus/aac) | Medium / Medium | Detect via `shutil.which`; exit 5 with per-OS hints; on first transcode failure with "Unknown encoder" give an actionable message naming the missing encoder (exit 5); CI runs against distro ffmpeg and Homebrew ffmpeg; no bundling (OQ2). |
| R3 | **Format availability varies** (no 44.1k AAC, no avc1 at 1080p, SABR-only or PO-token-restricted clients returning fewer formats) | Medium / Medium | Pure selector with documented fallbacks and stderr notices; strict mode for exactness; `--list-formats` for diagnosis; `Xtractor: no downloadable formats` -> exit 3 with explanation (and update hint) rather than crash. |
| R4 | **Legal / ToS exposure** | Medium / High | Notice in `-h` and README (T1.2, T7.1, T7.2 test); no DRM options, `allow_unplayable_formats` never set, DRM formats rejected (exit 3); no cookie/auth support in v1; no playlist/bulk mode; license and notice reviewed before the public release. |
| R5 | Bot checks ("Sign in to confirm you're not a bot") block anonymous downloads from some IPs | Medium / Medium | Map to exit 3 with a clear message; do not add cookie handling in v1 (spec non-goal); document in troubleshooting. |
| R6 | Partial files / race conditions on Ctrl-C | Low / Medium | Temp dir in destination dir, `finally` cleanup, signal handlers, tests (T6.2). |
| R7 | Python 3.9 on user machines (macOS system python) | Medium / Low | `requires-python>=3.10` gives pip's clear error; README says `pipx install --python python3.12`. |
| R8 | Filename edge cases (long titles, unicode normalisation, case-insensitive collisions) | Medium / Low | Sanitiser with byte-length cap, NFC normalisation, existing-file check via `os.path.exists` on case-insensitive FS. |
| R9 | Licence of the live-test video changes or video is removed | Low / Low | Choose a long-lived Blender/NASA/archive.org-mirrored CC video; smoke test skips (not fails) on exit 3 and the scheduled job reports it. |
| R10 | Spec ambiguity drift between help text and README | Low / Low | Help is generated from the parser; README option table is checked by a test against `-h`. |

---

## 6. Definition of done and release

**Definition of done (per task):** code merged via PR with tests; `ruff`, `mypy --strict` and `pytest` green on CI matrix; no new stdout writes outside the single permitted site; new user-visible messages documented; spec IDs in the task table still satisfied.

**Definition of done (v1.0):**
1. All "Must" requirements (F1-F5, F9, F10) and "Should" (F6-F8) implemented; F11/F12 optional.
2. Acceptance criteria AC1-AC10 verified: AC1, AC2, AC5, AC9 by automated tests; AC3, AC4 by real-ffmpeg tests and live smoke; AC6, AC7 by live smoke plus manual QuickTime check; AC8, AC10 by automated tests and one manual Ctrl-C run.
3. Coverage >=85% on non-I/O modules; mypy strict clean; ruff clean.
4. README complete (install, usage, defaults rationale, exit codes incl. 130, troubleshooting, legal notice); `-h` matches the spec layout with the legal notice.
5. Manual verification on macOS (Apple Silicon, plus Intel if available) and Ubuntu; Windows best-effort run noted in release notes (not blocking).
6. Spec issues S1-S14 resolutions recorded: update `PRODUCT_SPEC.md` to v0.2 (or an appendix) so spec and behaviour agree.

**Release steps**
1. Branch `release/1.0.0`; bump `__version__` and `pyproject.toml` (single source: `hatch` dynamic version from `__init__.py`); changelog entry.
2. Run full CI + `XTRACTOR_LIVE=1 pytest -m live` locally with the latest yt-dlp; complete the T8.3 checklist.
3. `python -m build`; install the wheel in a fresh venv and via `pipx install .`; verify `Xtractor --version`, `-h` without ffmpeg, and one real audio extraction.
4. Tag `v1.0.0`, push; GitHub release with sdist/wheel attached. Install doc: `pipx install git+https://github.com/<owner>/Xtractor@v1.0.0`.
5. Post-1.0 (optional): publish to PyPI (trusted publishing from `release.yml`), then a Homebrew tap formula (`depends_on "ffmpeg"`, `depends_on "python@3.12"`), then M9 items.
6. Maintenance: a patch release process for yt-dlp floor bumps (bump `>=`, run live suite, tag), triggered by the scheduled job's failures.
