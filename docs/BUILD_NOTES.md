# Build notes: single-file arm64 binary (milestone M10, build half)

Date: 2026-10-22. Host: Apple Silicon, macOS 27.0.1, Homebrew Python 3.12.15, PyInstaller 6.22.3,
yt-dlp 2026.10.21, yt-dlp-ejs 0.8.0. Numbers below are measured on this machine with
`scripts/measure_startup.sh` and `scripts/accept_binary.sh` (RUNS=10).

## 1. How to build

```sh
pip install -e '.[dev,build]'          # once (.venv); PyInstaller is pinned in the `build` extra
scripts/build_binary.sh                 # builds ffmpeg + fetches the JS runtime if missing, then:
                                        #   dist/Xtractor  dist/Xtractor-<ver>-macos-arm64.tar.gz  dist/SHA256SUMS
RUNTIME=deno scripts/build_binary.sh    # embed deno 2.9.8 instead of quickjs-ng 0.17.0
scripts/accept_binary.sh                # 15 checks against Caminandes 3 (SkVqJ1SGeL0) with PATH=/usr/bin:/bin
scripts/measure_startup.sh              # size, cold/warm -h and --version, extraction cost, budget check
```

| Script | Purpose |
|---|---|
| `scripts/build_ffmpeg.sh` | Pinned ffmpeg 9.0.2 + LAME 3.100 + Opus 1.6.1 (sha256-verified), minimal static LGPL build. Writes `build/ffmpeg`, `build/ffprobe`, `build/BUILDINFO-ffmpeg.json`. Fails if the build is not LGPL, has GPL/nonfree flags, or links a non-system dylib. About 70 s. Bit-for-bit reproducible here (two builds, same SHA-256). |
| `scripts/fetch_js_runtime.sh` | quickjs-ng 0.17.0 (default) or deno 2.9.8, pinned URL + sha256, version-checked. `build/js/`, `build/BUILDINFO-js.json`. |
| `scripts/build_binary.sh` | Stage tools, PyInstaller (`packaging/xtractor.spec`), sign, flat tarball + `SHA256SUMS`. Honors `RUNTIME`, `VERSION`, `PYTHON`, `SIGN_IDENTITY`, `SOURCE_DATE_EPOCH`. |
| `scripts/sign.sh` | Ad-hoc by default (P1). `SIGN_IDENTITY="Developer ID Application: ..."` selects a hardened-runtime path with `packaging/entitlements.plist` and optional notarization (`NOTARY_PROFILE`). The Developer ID path is structured but UNTESTED (no identity available). |
| `scripts/release_tools.py` | Writes the tool manifest and the generated blob module; builds the reproducible tarball (flat: `Xtractor`, `LICENSE`, `THIRD_PARTY_NOTICES`, as `--self-update` and the Homebrew formula expect). |

Embedded runtime choices: ffprobe is built (for verification) but **not embedded**: Xtractor never calls
it and yt-dlp falls back to `ffmpeg -i` parsing; merging, fixups and metadata all work without it
(verified by the acceptance run). It would add 5.9 MB.

ffmpeg additions found by testing the real thing (beyond the spike's list): the **mpegts demuxer** was
missing, which broke `-v` whenever YouTube served the 720p stream over HLS (format 232): "Error opening
input files: Invalid data found". Fixed in `build_ffmpeg.sh`. Stripped sizes: ffmpeg 6.07 MB, ffprobe 5.86 MB.
Network protocols stay disabled (no ffmpeg-side HLS/DASH download, so live streams are unsupported).

## 2. How the tools are embedded and found

- `scripts/release_tools.py` turns `ffmpeg` and `qjs` into bytes constants in a generated module
  `xtractor_blob` (plus a JSON manifest with name, size, SHA-256). PyInstaller stores it in the PYZ.
  I first shipped the tools as binaries/data; that works but a `--onefile` unpacks those to a fresh temp dir on
  every launch. Moving them into the PYZ removed that per-launch cost.
- `src/xtractor/bundle.py` (new): on first use extracts to
  `~/Library/Caches/Xtractor/<app-version>-<sha8 of the asset hashes>/` (dir mode 0700), one atomic
  temp file + `os.replace` per file (safe under concurrent runs), `chmod 755`, hash-checked before
  and after, ad-hoc `codesign` re-applied only if `codesign --verify` fails on the copy. Every later start
  re-verifies the SHA-256 of the file it uses (4 ms for both files) and re-extracts once if it is missing,
  truncated, modified or not executable. If that fails: exit 5 with a hint naming the escape hatch.
  `XTRACTOR_CACHE_DIR` overrides the cache root (tests, sandboxes).
- Resolution order (`ffmpeg.locate_ffmpeg`, `tools.locate_js_runtime`): bundled build -> embedded copy
  first, then `$PATH`. `XTRACTOR_USE_SYSTEM_TOOLS=1` flips this ($PATH first, embedded as fallback). Non-frozen
  (dev) runs have no bundle and keep the old behaviour (PATH only). JS runtime is always passed to yt-dlp with
  an explicit path (spike gotcha 1); `remote_components` stays empty.
- Excluded from the binary on purpose: `mutagen` (GPL-2.0-or-later, optional in yt-dlp), `websockets`,
  `Cryptodome` (38 extension files; yt-dlp falls back to pure-Python AES, only needed for encrypted HLS),
  CJK codecs, tkinter, unittest, pydoc, sqlite3, curses, etc. Together with the tool move, this took the extracted
  Mach-O files from 100 to 52 and the binary from 20.1 MB to 18.6 MB.
- Tests: `tests/unit/test_bundle.py` (first-run extract, reuse without rewrite, corruption, missing exec bit,
  unwritable cache -> exit 5, tampered bundle, bad manifest, 8 concurrent first runs, order of
  resolution incl. the opt-in env var), `test_release_tools.py` (blob round trip, reproducible tarball),
  `test_entry.py` (fast path output equals the CLI's).

## 3. Measurements (qjs build unless noted)

| Item | Result | Spec budget | Verdict |
|---|---|---|---|
| Binary size (quickjs-ng) | **18.6 MB** (tarball 18.5 MB) | <= 70 MB | met |
| Binary size (deno) | 56.4 MB (tarball 56.1 MB) | <= 120 MB | met |
| `--version` warm | median **0.86 s** (0.73-0.91) | <= 0.5 s | **BREACH** |
| `--version` cold (first launch of a fresh copy) | median 0.98 s | <= 1.5 s | met |
| `-h` warm | median **1.47 s** (1.39-1.52) | <= 0.5 s | **BREACH** |
| `-h` cold (first launch of a fresh copy) | median **1.54 s** (1.46-1.63) | <= 1.5 s | **BREACH** (marginal) |
| First launch right after a build | 4.9-5.2 s, once per freshly built file | n/a | one-off macOS scan |
| First-run tool extraction (ffmpeg + qjs) | 35 ms (write + hash), 4 ms to re-verify | n/a | negligible |
| Full audio extraction, `-a` m4a stream copy, 2.3 MB | **11.3 s** warm, 11.9 s with empty cache (qjs) | none in spec | see below |
| Same with the deno build | 6.1 s warm, 8.7 s first run | | |

"Cold" is a proxy: a fresh copy of the binary, first launch (new inode). A purged-cache cold start needs
`sudo purge`, which I did not run (no system changes).

### Why `--onefile` breaches the start-up budgets, and what helps

- A hello-world PyInstaller onefile already costs 0.46 s warm on this machine. Each extension module Python
  loads at start adds roughly 0.1 s (ssl +0.25 s, hashlib +0.15 s, subprocess +0.13 s), and each file the
  bootloader extracts about 15 ms: macOS re-checks the freshly written temp files at every launch. `--help` imports the
  whole CLI (including `selfupdate` -> ssl, http.client, tarfile; and subprocess/hashlib through ffmpeg/bundle).
- Done: `--version` has a fast path in `packaging/entry.py` (1.2 s -> 0.86 s); tools are in the PYZ; 40+ extension files removed.
- The same code built `--onedir`: `-h` **0.10 s**, `--version` **0.05 s** (first launch 5.3 s once), 30 MB. So the
  per-launch unpack is the entire problem. Build it with `XTRACTOR_ONEDIR=1 XTRACTOR_STAGE=build/stage pyinstaller packaging/xtractor.spec`.
- Remaining options, in order of effort: (1) make `cli.py` import `selfupdate`, `ytdlp`, `pipeline` lazily (the
  tests monkeypatch those names on `xtractor.cli`, so they need a matching change; owner of cli.py/selfupdate.py): saves
  about 0.5 s on `-h` (measured 1.46 -> 0.93 s on a reduced build); (2) ship the spec's own D1 fallback
  (onedir inside the tarball, needs the self-update and Homebrew contract to change from one file to a directory);
  (3) a tiny launcher that unpacks an onedir payload once into the cache and `exec`s it, which keeps one file and gives
  about 0.1 s warm (not built: C launcher plus signing a binary with a trailing payload needs its own spike).
  Recommendation: do (1) now and decide between (2) and (3) before the first release.

### Audio time is dominated by JS challenge solving, not by packaging

`-a` solves YouTube's JS challenge twice (probe, then download re-extracts): about 4.6 s each with quickjs-ng, about
2 s with deno. `RUNTIME=deno` cuts the audio run from 11.3 s to 6.1 s for +38 MB. Passing the probe's info dict into the
download (or enabling yt-dlp's challenge cache) would halve it for either runtime; that lives in `pipeline.py`/`ytdlp.py` flow design.

## 4. Acceptance run (qjs build, `PATH=/usr/bin:/bin`, empty cache): 15/15 pass

`-h`, `--version`; `-a` default (aac 44100 Hz m4a, ffmpeg command contains `-c:a copy`, `[jsc:quickjs]` solver ran);
`-a --sample-rate 48000 --audio-format wav` (pcm_s16le 48000); `-v --resolution 720` (h264 720p + aac, merged by the
embedded ffmpeg); `-v --resolution 1080 --video-format mkv` (h264 1080 + opus); `--list-formats` (43 lines incl. ids 140/251, which only
exist when the JS runtime works); Ctrl-C mid-download: exit 130, no files left in the output directory, no leaked `_MEI*`
temp dir, no orphan child. The deno build also passes 15/15. Only video SkVqJ1SGeL0 was downloaded; all media is deleted by the script.

Observation: the default m4a path picked format `140-drc` (dynamic-range-compressed AAC) as "bestaudio"; pipeline's
format selector may want `140`/`bestaudio[format_note!*=DRC]`. Not a packaging matter, flagged for the owner.

## 5. Quarantined ad-hoc binary: what really happens (investigated on copies, nothing changed)

Method: copies of `dist/Xtractor` with `xattr -w com.apple.quarantine "0083;<time>;Safari;<uuid>"` (what a browser sets), run
non-interactively with the unified log open.

- The process is **never started**. The kernel's AppleSystemPolicy refuses the exec ("Security policy would not allow
  process"), `syspolicyd` evaluates the file, finds no notarization ticket and no Developer ID, **shows a Gatekeeper
  prompt and waits for the user's answer**, then kills the process: "Terminating process due to Gatekeeper rejection".
  The caller sees no output and exit status 137 / `SIGKILL`.
- The "hang" the spike saw is that wait: the first launch blocked for 99 s in one run (prompt unanswered), in another it was
  killed after 1-3 s. Launches of the same file after a rejection are killed within about 1 s. `spctl -a -t exec` says "rejected".
  Do not run the file again expecting it to work; nothing in Xtractor can fix this from the inside.
- The cache files that the binary writes itself (ffmpeg, qjs) are not quarantined, so they are not a problem.
- Removing the attribute fixes it at once (verified, same copy runs immediately): `xattr -d com.apple.quarantine <file>`.
- bsdtar and Archive Utility copy the quarantine flag from the downloaded archive onto the extracted files (verified), so clear it on
  the archive BEFORE extracting, or on the binary after.

**User-facing workaround (for the README owner):**

```sh
# Downloaded in a browser? Clear the quarantine flag before the first run:
xattr -d com.apple.quarantine ~/Downloads/Xtractor-*-macos-arm64.tar.gz   # before extracting
tar -xzf ~/Downloads/Xtractor-*-macos-arm64.tar.gz
# or, if you already extracted it:
xattr -d com.apple.quarantine ./Xtractor
```
If you answered the Gatekeeper dialog already, the first run was killed; clear the flag as above and run again. Installing via
`curl -L ... | tar xz`, `brew install`, or `Xtractor --self-update` never sets the flag. (System Settings > Privacy & Security >
"Open Anyway" also works for GUI-launched files, but is not reliable for a bare command-line binary.)

## 6. Licensing and notices

`THIRD_PARTY_NOTICES` (repo root, shipped in the tarball) covers ffmpeg/LAME (LGPL-2.1+, full text, source offer with pinned URLs and
checksums, exact build script, replaceability via `XTRACTOR_USE_SYSTEM_TOOLS=1`), Opus (BSD), quickjs-ng (MIT), yt-dlp and
yt-dlp-ejs (Unlicense + ISC/MIT parts), CPython/PyInstaller (bootloader exception), requests/urllib3/certifi etc. The notices state
that mutagen (GPL) is excluded. To check after a dependency bump: the "bundled libraries" table lists what PyInstaller collects; review it
with `pyi-archive_viewer -l -r dist/Xtractor`.

## 7. Open items

1. Start-up breaches in section 3: decision needed (lazy imports in cli.py, onedir tarball, or launcher).
2. Developer ID signing/notarization path in `sign.sh` is untested.
3. `build_binary.sh` relies on Homebrew's Python 3.12 (its libpython and OpenSSL dylibs are bundled); a python.org build should work but was not tried.
4. CI: `release.yml` must call `scripts/build_ffmpeg.sh` (needs `brew install pkgconf`) before `build_binary.sh`; it calls build_binary.sh
   which builds ffmpeg itself when `build/ffmpeg` is missing, so caching `build/ffmpeg` + `build/BUILDINFO-*.json` is optional.
5. Audio time (section 3) is dominated by two JS solves per run.
