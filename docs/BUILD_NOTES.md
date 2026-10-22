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
  temp file (`O_EXCL|O_NOFOLLOW`) + `os.replace` per file (safe under concurrent runs), `chmod 755`, hash-checked before
  and after (symlinks are never accepted), `/usr/bin/codesign` ad-hoc re-applied only if `--verify` fails on the copy.
  The cache root and version dir are forced to 0700 and must be owned by the user and not be symlinks; stale
  `<version>-<sha8>` siblings older than an hour are pruned after an extraction. Every later start
  re-verifies the SHA-256 of the file it uses (4 ms for both files) and re-extracts once if it is missing,
  truncated, modified or not executable. If that fails: exit 5 with a hint naming the escape hatch.
  `XTRACTOR_CACHE_DIR` (cache root) and `XTRACTOR_BUNDLE_DIR` (tests) are ignored in a frozen build unless
  `XTRACTOR_ALLOW_OVERRIDES=1` is also set (`accept_binary.sh` and `measure_startup.sh` set it).
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
| `--version` warm | median **0.43 s** (0.39-0.45); was 0.86 s | <= 0.5 s | met |
| `--version` cold (first launch of a fresh copy) | median 0.58 s; was 0.98 s | <= 1.5 s | met |
| `-h` warm | median **0.50 s** (0.44-0.52); was 1.47 s | <= 0.5 s | **at the limit** (RUNS=10, 2026-10-23, after the --version/tool-version work) |
| `-h` cold (first launch of a fresh copy) | median 0.78 s; was 1.54 s | <= 1.5 s | met |
| First launch right after a build | 4.9-5.2 s, once per freshly built file | n/a | one-off macOS scan |
| First-run tool extraction (ffmpeg + qjs) | 30 ms (write + hash), 4 ms to re-verify | n/a | negligible |
| Full audio extraction, `-a` m4a stream copy, 2.3 MB | **6.1 s** warm (qjs binary, acceptance run); was 11.3 s | none in spec | see below |
| Same, dev venv with quickjs-ng / deno on PATH | 4.85 s / 2.4 s; was 9.2 s / 4.45 s | | challenge solved once |

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
- Update (post-fix, quickjs-ng build, RUNS=10): the budgets are met. Two changes did it, in this order:
  1. `cli.py` imports `pipeline`, `selfupdate`, `ytdlp`, `tools`, `ffmpeg` inside the functions that need them (plus
     `ui` -> `ytdlp` under `TYPE_CHECKING`, `shutil`/`tempfile` lazy in `paths.py`). `-h`/`--version` no longer load
     subprocess, hashlib, ssl, shutil, tempfile or yt_dlp (`test_help_and_version_do_not_import_heavy_modules`
     enforces it). `-h` warm 1.47 -> 0.74 s, `--version` 0.86 -> 0.70 s.
  2. `packaging/xtractor.spec` excludes 12 more extension modules whose users have fallbacks or guards (`_lzma`+liblzma,
     `_bz2`, `_pickle`, `_statistics`, `_sha1`, `_md5`, `_sha3`, `_multiprocessing`, `_posixshmem`, `mmap`, `resource`, `grp`),
     verified against the extension modules a real `-a` run loads and by the 15-check acceptance run (15/15 pass).
     Each file the bootloader unpacks costs about 15-20 ms per launch, so `-h` warm 0.74 -> 0.45 s, `--version` 0.70 -> 0.38 s.
  The margin on `-h` warm is gone (0.44-0.52 s vs 0.5 s after the version/self-test work; `--version` now also prints the
  bundled tool versions from the generated `xtractor_buildinfo` module, no subprocess) and will shrink with every new extension module. `python -X importtime`
  of `-h` is now about 23 ms of imports (argparse 4 ms, options/paths 14 ms): further wins can only come from fewer unpacked files.
  strip/UPX were not applied (strip invalidates the signature, UPX is not allowed). The bootloader has no option to cache the unpack.
- If the budget is lost again (a new dependency, or slower disks), the options are, in order of effort: (a) ship the
  spec's D1 fallback, onedir inside the tarball (`-h` 0.10 s; needs the self-update and Homebrew contract to change from one
  file to a directory); (b) a tiny launcher that unpacks an onedir payload once into `~/Library/Caches/Xtractor` and
  `exec`s it (one file, about 0.1 s warm). NOT built and NOT adopted: it needs a C launcher with a trailing payload,
  which breaks the ad-hoc/Developer ID signature of the file unless the payload is a signed Mach-O section, so it needs its own spike.

### Audio time was dominated by JS challenge solving, not by packaging (fixed)

Cause: `pipeline.run` calls `probe` and then `download`, and each used its own `YoutubeDL.extract_info(url)`, so the extractor
ran twice and YouTube's JS challenge (n/sig) was solved twice (the `[jsc:...] Solving JS challenges` line appeared twice).
Fix (`ytdlp.py`): `probe` calls `extract_info(url, download=False, process=False)` (the extractor's raw result, challenge solved
here), keeps that dict per video id and builds `MediaInfo` from `process_ie_result(copy.deepcopy(raw), download=False)`.
`download` then calls `process_ie_result(copy.deepcopy(raw), download=True)` on a fresh `YoutubeDL` carrying the download params: only
format selection and the transfer run. Keeping the RAW dict matters: feeding back an already format-processed dict (default
selector `bv*+ba`) made the next selection (`140`) inherit fields of the first one and YouTube returned HTTP 403. If probe returns a
playlist the download falls back to a fresh extraction.

| `-a` m4a copy, SkVqJ1SGeL0 (dev venv, runtime on PATH) | before | after |
|---|---|---|
| quickjs-ng 0.17.0 | 9.5 / 9.0 s | 4.9 / 4.8 s |
| deno 2.9.8 | 4.5 / 4.4 s | 2.3 / 2.5 s |
| quickjs binary, acceptance run | 11.3 s | 6.1 s |

The solver now runs once (one `Solving JS challenges` line). Remaining time is quickjs-ng being about 2x slower than deno at the
solve (+38 MB for deno).

## 4. Acceptance run (qjs build, `PATH=/usr/bin:/bin`, empty cache): 15/15 pass

`-h`, `--version`; `-a` default (aac 44100 Hz m4a, ffmpeg command contains `-c:a copy`, `[jsc:quickjs]` solver ran);
`-a --sample-rate 48000 --audio-format wav` (pcm_s16le 48000); `-v --resolution 720` (h264 720p + aac, merged by the
embedded ffmpeg); `-v --resolution 1080 --video-format mkv` (h264 1080 + opus); `--list-formats` (43 lines incl. ids 140/251, which only
exist when the JS runtime works); Ctrl-C mid-download: exit 130, no files left in the output directory, no leaked `_MEI*`
temp dir, no orphan child. The deno build also passes 15/15. Only video SkVqJ1SGeL0 was downloaded; all media is deleted by the script.

Observation (fixed): the default m4a path picked format `140-drc` (dynamic-range-compressed AAC) as best audio because its
bitrate is marginally higher. `formats.select_audio` now ignores DRC variants (format_id ending `-drc`, or "DRC" in
`format_note`/`format`) unless nothing else exists. Verified live on Caminandes 3 (SkVqJ1SGeL0): `Downloading 1 format(s): 140`,
output aac LC 44100 Hz 128 kb/s, ffmpeg `-c:a copy`; media deleted afterwards.

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

1. Developer ID signing/notarization path in `sign.sh` is untested (no identity). Entitlements were verified with ad-hoc
   hardened-runtime copies, see section 8.
2. `build_binary.sh` relies on Homebrew's/setup-python's Python 3.12 (its libpython and OpenSSL dylibs are bundled); the release
   workflow uses `actions/setup-python` and `brew install pkgconf` for `build_ffmpeg.sh`. Neither has run on a GitHub runner yet:
   the first tag (or a `workflow_dispatch` dry run) is the test.
3. `-h` warm start-up is at the 0.5 s budget; the next extension module or import will break it (section 3 lists the options).
4. `ffprobe` is built but not embedded (section 1).

## 8. Release process, signing and security notes

**Trust root.** `--self-update` accepts a release only if `SHA256SUMS.sig` (base64 Ed25519 signature over
`b"Xtractor-release-v1\n" + SHA256SUMS`) verifies against a public key in `TRUSTED_PUBLIC_KEYS` (`src/xtractor/selfupdate.py`).
The signed tarball name carries the version, which must equal the release tag, so a replayed old release is refused; downloads
are https-only, pinned to GitHub hosts, capped (200 MB, 15 min). Forks must embed their own key.
- Generate once: `scripts/gen_signing_key.py` (private seed to `~/.config/xtractor-signing/ed25519.key`, mode 0600, never printed;
  prints the public key hex). Back the key file up offline.
- Store in GitHub: `gh secret set XTRACTOR_SIGNING_KEY --env release < ~/.config/xtractor-signing/ed25519.key`
  (create the `release` environment with required reviewers first). The `publish` job runs `scripts/sign_release.py` and **fails
  the tag release if the secret is missing**.
- Rotation: add the new public key to `TRUSTED_PUBLIC_KEYS`, ship a release signed with the OLD key, then sign later releases with
  the new key, and remove the old key in a still later release.
- Rollback of a stolen key: ship a release whose binary has the key replaced; users must reinstall manually (there is no revocation
  channel), which is why the key lives only in a protected environment.

**Dependencies.** `requirements-build.txt` (hashes, `pip-compile --generate-hashes`, regenerate from `requirements-build.in` on
macOS arm64 / Python 3.12) is installed with `--require-hashes --no-deps` by `release.yml`. `constraints-ci.txt` pins the CI matrix.
Actions are pinned to commit SHAs (Dependabot refreshes them). Artifact attestations (`actions/attest-build-provenance`) run only
when the repository is public (they need a public repo or GitHub Enterprise Cloud); verify with `gh attestation verify`.

**Release gate.** Tag must match `vX.Y.Z[-alpha|beta|rc.N]`, be on `main`, and equal `__version__`. The build job's offline smoke test
runs `dist/Xtractor --xtractor-selftest` (env `XTRACTOR_SELFTEST=1`): extracts the embedded tools, round-trips audio through the embedded
ffmpeg (m4a, opus, flac, mp3, wav, mkv remux), runs the embedded JS runtime and imports `yt_dlp_ejs`. The network acceptance run
(`scripts/accept_binary.sh`) stays a manual step (YouTube is flaky from CI IP ranges); run it before tagging.

**Compliance assets.** Each release also uploads `BUILDINFO-ffmpeg.json`, `BUILDINFO-js.json`, `build_ffmpeg.sh` and `common.sh`.

**Entitlements (F-15, tested 2026-10-23).** Ad-hoc signed copies of the binary with `--options runtime`: without
`disable-library-validation` the binary does not start (different Team IDs for the extracted libpython); without
`allow-unsigned-executable-memory` everything works (`--version`, `--list-formats`, `-a`, `-v`, self-test), so it was removed from
`packaging/entitlements.plist`. The embedded runtimes are separate processes: hardened `ffmpeg` and `qjs` need no entitlements;
hardened `deno` crashes without `com.apple.security.cs.allow-jit` (`packaging/entitlements-deno.plist`, sign deno with it).
The Developer ID + notarization path itself is still untested.
