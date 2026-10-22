# Packaging spike: single self-contained arm64 macOS binary (yt-dlp + JS runtime + ffmpeg)

Date: 2026-10-22. Host: arm64 macOS (Darwin 27), Homebrew Python 3.12.
Versions: yt-dlp 2026.10.21, yt-dlp-ejs 0.8.0, PyInstaller 6.22.3, deno 2.9.8, node 24.22.1,
quickjs-ng 0.17.0, FFmpeg 9.0.2 (built from source), LAME 3.100, Opus 1.6.1.
Test video: Blender "Big Buck Bunny" official upload, `https://www.youtube.com/watch?v=YE7VzlLtp-4`
(597 s). Note: yt-dlp reports `license: None` (YouTube "standard licence" flag), although Blender
releases the film under CC-BY 3.0. Use something flagged CC on YouTube for any redistributable fixtures.
All downloaded media was deleted after the tests (only a 28 MB audio file, from the test video).

## Verdict: GO, with conditions

A single self-contained arm64 binary works end to end. The frozen binary found and executed the
embedded JS runtime and the embedded ffmpeg, and downloaded an audio-only m4a (verified with
ffprobe) even with `PATH=/usr/bin:/bin`, where no system ffmpeg, node or deno exists.

- Recommended runtime: **quickjs-ng** if size is the priority, **deno** if speed is (see section 4).
- Do **not** ship `--onefile` for the interactive path: warm `--help` takes about 1.4 s, against 0.11 s
  for `--onedir`. Ship `--onedir` inside an app bundle or installer, or accept a cache-extracted onefile.
- A JS runtime is **mandatory for usable audio**. Without one, the best audio formats are missing.
- Signing and notarization are required for distribution. A quarantined ad-hoc binary hung on exec.
- The Homebrew ffmpeg cannot be bundled (GPL, dynamic). A custom LGPL static build is 5.8 MB and works.

## 1. yt-dlp API (read from the installed source)

Library options for `yt_dlp.YoutubeDL(params)`, from `yt_dlp/YoutubeDL.py` (docstring around line 543):

```python
opts = {
  # dict: runtime name (lower-case) -> config dict. Supported names: 'deno', 'node', 'bun', 'quickjs'
  # config keys: 'path' = path to the executable (file) OR a directory containing it
  'js_runtimes': {'quickjs': {'path': '/abs/path/to/qjs'}},
  # list of allowed remote component sources: 'ejs:github', 'ejs:npm'. Default: none allowed.
  'remote_components': [],
  'ffmpeg_location': '/abs/dir/containing/ffmpeg-and-ffprobe',   # or a path to the ffmpeg binary
}
```

- Default when `js_runtimes` is absent: `{'deno': {}}`. Pass `{}` to disable all runtimes.
- CLI equivalents: `--js-runtimes RUNTIME[:PATH]` (repeatable), `--no-js-runtimes`,
  `--remote-components ejs:github`.
- Priority when several are enabled and available: deno, node, quickjs, bun. The first available wins.
  To force a lower-priority one, enable only that one.
- Runtime names: `quickjs` selects `qjs` (quickjs-ng or Fabrice's quickjs). Basename searched when no
  path is given: `deno`, `node`, `bun`, `qjs`.
- Gotcha: `_find_exe` (yt_dlp/utils/_jsruntime.py) only searches the Python scripts dir, then the bare
  name on `PATH`. Its frozen-exe-directory search is Windows-only (`os.name != 'nt'` returns early). A
  bundled binary on macOS is therefore **only** found if you pass `path` explicitly. Do this always.
- Version detection: yt-dlp runs `<runtime> --version` (`--help` for qjs, which exits 1 and is
  tolerated). A runtime that cannot execute is silently "unavailable", and the provider list in
  `-v` output shows `deno (unavailable)`.
- Minimum versions: node >= 23.5.0 warned below; quickjs-ng any version supported, plain quickjs >=
  2023-12-09; deno was fine at 2.9.8.
- `remote_components` is **not needed** when the `yt-dlp-ejs` package is installed. The solver scripts
  come from the package (`[jsc:deno] Using challenge solver lib script v0.8.0 (source: python package,
  variant: minified)`). Leave it empty so the app never fetches code from the network at runtime.
- The solver lives in `yt_dlp_ejs/yt/solver/{core,lib}.min.js` (package data) and also vendored
  fallbacks in `yt_dlp/extractor/youtube/jsc/_builtin/vendor/`. PyInstaller needs the data files:
  `--collect-all yt_dlp_ejs`.

Probe script: `spike/probe.py` (library, `download=False`) and `spike/xprobe.py` (frozen-aware CLI).
Both live in the scratch dir, not in the repo.

### Probe results (venv, 2 runs each, wall time of `extract_info`)

| Runtime | Formats | Extract time | Notes |
|---|---|---|---|
| none (`js_runtimes={}`) | 43 | 1.2-1.3 s | Warning: "No supported JavaScript runtime could be found ... some formats may be missing" |
| deno 2.9.8 | 49 | 2.2-2.3 s | Full set |
| node 24.22.1 | 49 | 2.2 s | Full set |
| quickjs-ng 0.17.0 | 49 | 4.6-4.7 s | Full set, about 2x slower than deno/node |

Format diff, JS vs no JS. Without a runtime these formats are **missing**: `18` (360p muxed),
`140` (AAC 128k m4a), `251` (Opus webm), `140-drc`, `251-drc`, `229`, plus AI-upscaled `248-sr` and
`399-sr`. They are replaced by low-quality variants. The no-JS list keeps only
`139` (low AAC) and `249/250` (low Opus) as audio, so `bestaudio` quality drops. With JS
the extra IDs are `18 256 258 328 380 773`. Max height is 1080 in both cases.
Every format had a direct `url` in both cases. The loss is of the preferred client's formats,
not of URLs.

## 2. PyInstaller build and measurements

Commands (venv at `spike/venv`; staged tool dirs hold `ffmpeg`, `ffprobe` and one runtime):

```sh
venv/bin/pyinstaller --noconfirm --clean --onefile|--onedir --name xprobe_<rt>_<mode> \
  --collect-all yt_dlp_ejs --collect-submodules yt_dlp \
  --hidden-import yt_dlp.compat._legacy --hidden-import yt_dlp.compat._deprecated \
  --hidden-import yt_dlp.utils._legacy  --hidden-import yt_dlp.utils._deprecated \
  --add-binary "stage_<rt>/ffmpeg:bin" --add-binary "stage_<rt>/ffprobe:bin" \
  --add-binary "stage_<rt>/<deno|qjs>:bin"  xprobe.py
```

The hidden imports mirror yt-dlp's own `bundle/pyinstaller.py` (the `_legacy`/`_deprecated` modules
are loaded by name). yt-dlp's official build also collects submodules and `certifi`. The `[default]`
extra pulls `brotli`, `certifi`, `mutagen`, `pycryptodomex`, `requests`, `urllib3`, `websockets` and
`yt-dlp-ejs`, and PyInstaller's hooks picked them up without extra flags. Build time was 15-22 s.

Resolving bundled tools at runtime:

```python
base = getattr(sys, '_MEIPASS', dirname(abspath(__file__)))     # onefile: temp extraction dir; onedir: _internal
qjs  = os.path.join(base, 'bin', 'qjs')
opts = {'js_runtimes': {'quickjs': {'path': qjs}}, 'ffmpeg_location': os.path.join(base, 'bin')}
```

PyInstaller 6 places `--add-binary` files at `<_MEIPASS>/bin/`. In onedir, `_MEIPASS` is `<dir>/_internal`.
The execute bit is preserved. The alternative of copying to `~/Library/Caches/Xtractor-spike` also worked
(`--cache-extract`): copy once, and check the size before re-copying.

### Sizes

| Variant | Size |
|---|---|
| onefile + quickjs-ng + ffmpeg (5.9 MB) + ffprobe | **25.7 MB** |
| onefile + deno + ffmpeg + ffprobe | **63.4 MB** (deno is 81.5 MB raw, 38.7 MB gzipped) |
| onedir + quickjs | 47 MB |
| onedir + deno | 123 MB |
| node (not built) | the binary is 122.5 MB raw, 39.3 MB gzipped, so it would be about 66 MB onefile |

Component sizes: yt_dlp package 24 MB on disk (all extractors), ffmpeg 5.98 MB, ffprobe 5.76 MB,
qjs 1.3 MB.

### Startup (arm64, M-series, `--help` x5 warm; "first" = first run after build)

| Variant | First | Warm |
|---|---|---|
| onefile + qjs | 5.55 s | 1.31-1.45 s |
| onefile + deno | 2.24 s | 1.56-1.71 s |
| onedir + qjs | 1.50 s | 0.11-0.12 s |
| onedir + deno | 1.40 s | 0.11-0.12 s |

Onefile pays the extraction of about 50-120 MB to `/var/folders/.../T/_MEI*` on **every launch**. The
first-run spike (5.5 s) comes from macOS scanning a new unsigned binary. A truly cold disk cache was not
measurable, because `purge` needs sudo and system state must not be changed.

### Full probe (`extract_info`, frozen, download=False; real = whole process, warm)

| Variant | Process wall time | Of which `import yt_dlp` + startup |
|---|---|---|
| onefile + qjs | 7.8 s (11.8 s first run) | 1.4 s |
| onedir + qjs | 4.8-4.9 s | 0.11-0.14 s |
| onefile + deno | 6.2-6.6 s | 1.4 s |
| onedir + deno | 2.5 s | 0.11-0.14 s |

All returned 49 formats, which proves the frozen binary located and executed the embedded runtime (the
no-JS result is 43).

### Download and ffmpeg proof

```sh
env -i HOME=$HOME PATH=/usr/bin:/bin dist_qjs/xprobe_qjs_onefile \
  'https://www.youtube.com/watch?v=YE7VzlLtp-4' --rt quickjs --download-audio <dir>
```

With `PATH` containing only `/usr/bin:/bin` (no ffmpeg, node or deno on it), this downloaded `bestaudio[ext=m4a]`
(format 140, 27.6 MiB), ran the yt-dlp fixup via the embedded ffmpeg, and finished. `ffprobe`
(the self-built one) reported: `codec_name=aac, sample_rate=48000, channels=6, format=mov,mp4,m4a,3gp,3g2,mj2,
duration=596.544`, byte-identical to the download made from the unfrozen venv, with the `Lavf63.1.102` encoder tag.
`--selftest` also exec'd the bundled `ffmpeg -version`, `ffprobe -version`, `qjs --help` and `deno --version`
from `_MEIPASS`. The deno onefile variant with `--cache-extract` (tools copied to
`~/Library/Caches/Xtractor-spike`) also downloaded and verified OK. (The cache dir is left in place; delete it
if tidy-up is wanted.)

Gotcha: `fixup: 'force'` makes yt-dlp run `ffmpeg -c copy` on DASH m4a. By default (`detect_or_warn`)
it only runs when a defect is detected, so a plain audio download may not touch ffmpeg at all.

### Code signing, Gatekeeper, quarantine

- PyInstaller output is ad-hoc signed (`codesign -dv`: `Signature=adhoc`, `TeamIdentifier=not set`,
  flags `0x2(adhoc)`). `spctl -a -vv -t exec` says **rejected** for all variants, as expected.
- The bundled deno has its own Developer ID-less hardened-runtime signature (`flags=0x10000(runtime)`);
  qjs and the self-built ffmpeg are ad-hoc/linker-signed arm64. PyInstaller re-signs collected binaries ad hoc.
- Quarantine: I applied `com.apple.quarantine` to a **copy** of the binary (no system settings changed).
  Running it from this non-interactive session **hung** (killed by a 25 s alarm), and a second fresh copy
  launched immediately afterwards also hung until I killed it. A third fresh copy ran normally. So treat an
  unsigned, quarantined binary as blocking at exec (Gatekeeper assessment waits for user action), and
  assessments can stall later first-launches. Caveat: the second hang is not fully explained.
  Binaries fetched with `curl` carry no quarantine; browsers, AirDrop and Mail add it.
- Required for distribution: sign with a Developer ID Application cert with hardened runtime, notarize,
  staple, ship as a signed `.pkg` or `.dmg`/`.app`. Every nested Mach-O (deno, qjs, ffmpeg, the Python
  libs inside onefile) must be signed individually. For a hardened-runtime Python app, the entitlements
  `com.apple.security.cs.allow-unsigned-executable-memory` or `disable-library-validation` may be needed,
  depending on the framework build. Not tested here (no signing identity).
- Onefile extracts executables at run time into `$TMPDIR`. Notarization covers only the outer binary, and
  extracted children are checked by their embedded signatures, so sign them before bundling.

## 3. Minimal LGPL ffmpeg

Homebrew ffmpeg 9.0.2 cannot be shipped:
- It is built with `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 ...` (GPL), so it
  is unsuitable for a closed or permissively licensed app.
- It is **not** a single file. The 426 KB `ffmpeg` links `libavdevice/avfilter/avformat/avcodec/swresample/
  swscale/avutil` (16 MB of dylibs) plus 37 `otool -L` entries including `libvmaf`, `openssl@4`, `libvpx`,
  `liblzma`, `dav1d`, `libmp3lame`, `libopus`, `libSvtAv1Enc`, `x264`, `x265` and many system frameworks.
  Bundling means relocating a dozen dylibs with `install_name_tool`.

Third-party static arm64 builds (reachable, HTTP 200 on 2026-10-22; **not** audited here): martin-riedl.de/ffmpeg
(static snapshot/release builds for macOS arm64, plus `.zip`/`.pkg` and sha256 files), osxexperts.net,
evermeet.cx/ffmpeg. These are commonly GPL builds. Check `ffmpeg -version | grep enable-gpl` and
`ffmpeg -L` before using any of them.

### Source build (done, works)

Source: `https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz`. Prerequisites: `brew install pkgconf`;
LAME 3.100 was built from source because the Homebrew `libmp3lame.a` needs `libmpg123` (it fails
to link statically otherwise):

```sh
# LAME (static, no decoder, no frontend)
./configure --prefix=$PWD/../lame-static --disable-shared --enable-static --disable-frontend --disable-decoder
# put libmp3lame.a, libopus.a (from brew) and a relocated opus.pc in a dir with NO dylibs, so the linker
# is forced to pick the .a files, then:
PKG_CONFIG_PATH=<that>/lib/pkgconfig ./configure --prefix=$PWD/install --cc=clang --arch=arm64 --target-os=darwin \
  --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-network \
  --disable-ffplay --enable-ffmpeg --enable-ffprobe --disable-shared --enable-static \
  --enable-libmp3lame --enable-libopus --enable-zlib \
  --extra-cflags="-I<static>/include" --extra-ldflags="-L<static>/lib -Wl,-dead_strip" \
  --enable-protocol=file,pipe,fd \
  --enable-demuxer=mov,matroska,ogg,mp3,flac,wav,aac,image2,image2pipe,image_jpeg_pipe,image_png_pipe,image_webp_pipe,concat,ffmetadata,opus \
  --enable-muxer=matroska_audio,mp4,ipod,mov,matroska,webm,ogg,opus,mp3,flac,wav,adts,null,image2,mjpeg,ffmetadata,mpegts \
  --enable-decoder=aac,aac_fixed,mp3,mp3float,opus,libopus,vorbis,flac,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8,webp,png,mjpeg \
  --enable-encoder=aac,libmp3lame,libopus,flac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,mjpeg,png \
  --enable-parser=aac,aac_latm,opus,vorbis,flac,mpegaudio,h264,hevc,vp9,av1,mjpeg,png,webp,vp8 \
  --enable-bsf=aac_adtstoasc,extract_extradata,h264_mp4toannexb,hevc_mp4toannexb,vp9_superframe,vp9_superframe_split,null,opus_metadata \
  --enable-filter=aresample,anull,null,aformat,format,scale,atrim,trim,volume,loudnorm,afade,atempo,pan,amix,anullsrc,anullsink,nullsink,setpts,asetpts,crop,pad,amerge,channelmap
make -j8      # about 15 s on this machine (8 jobs)
strip -x ffmpeg ffprobe
```

Result: configure prints `License: LGPL version 2.1 or later`. `ffmpeg` is **5.98 MB** and `ffprobe` **5.76 MB** (stripped),
against 426 KB plus 16 MB of dylibs for Homebrew. `otool -L` shows only `libSystem`, `libz`, `CoreFoundation`,
`CoreVideo`, `CoreMedia` (system), so it is fully static with respect to third-party code.
Both are ad-hoc (linker-signed) and run in place.

Caveats: `--disable-network` means no https, and so no ffmpeg-side HLS/DASH download. yt-dlp's native
downloader fetches over HTTP itself, so the audio/video merge path is unaffected, but formats that need
`-protocol_whitelist` / ffmpeg HLS (live streams, some m3u8) would need `--enable-network` plus a TLS backend
(`--enable-securetransport` is deprecated; a static OpenSSL or mbedTLS would add 1-3 MB). Opus and LAME
licence texts (BSD / LGPL) must be shipped with the app, and the LGPL requires the ffmpeg and LAME source
(or an offer for it) plus the build script, and that the user can relink. A static link is allowed only if
object files or equivalent are provided, which is why a separate executable (as here) is the safe route.

### Tested command set (20 s slice of the 596 s 5.1 channel AAC m4a, all verified with the self-built ffprobe)

| Command (after `-hide_banner -loglevel error -y -t 20 -i in.m4a`) | Result |
|---|---|
| `-vn -c:a copy out.m4a` | OK, aac 48 kHz 6ch, 971,605 B |
| `-vn -ar 48000 -c:a pcm_s16le out.wav` | OK, pcm_s16le 48 kHz 6ch |
| `-vn -c:a libmp3lame -b:a 192k out.mp3` | OK, mp3 48 kHz 2ch, 481,679 B |
| `-vn -c:a libopus -b:a 128k out.opus` | OK, opus 48 kHz 6ch (ogg) |
| `-vn -c:a libopus out.ogg` | OK |
| `-vn -c:a flac out.flac` | OK |
| `-vn -c:a libopus out.mka` | OK after adding `matroska_audio` muxer (first build failed with "Unable to choose an output format") |
| `-c copy out.mp4` / `-c copy out.mkv` | OK (audio only input; video mux not tested, no video input, but the demuxers/muxers/parsers are enabled) |
| `-vn -c:a aac -b:a 128k out.m4a` | OK, native AAC encoder |
| `-vn -af aresample=44100,loudnorm -c:a libmp3lame out.mp3` | OK |

Not tested: thumbnail conversion (mjpeg/png/webp path is enabled but unexercised), video re-encode (none enabled, by
design: copy only, no libx264), subtitle conversion (no subtitle codecs enabled), `lavfi` inputs (no indev).

## 4. Runtime recommendation

| | deno 2.9.8 | node 24.22.1 | quickjs-ng 0.17.0 |
|---|---|---|---|
| Binary (raw / gz) | 81.5 / 38.7 MB | 122.5 / 39.3 MB | **1.3 / 0.6 MB** |
| Onefile app size | 63.4 MB | about 66 MB (est.) | **25.7 MB** |
| Challenge solve (extract_info) | 2.2 s | 2.2 s | 4.6 s |
| Full frozen probe, onedir | 2.5 s | n/a | 4.8 s |
| Formats | 49 | 49 | 49 |
| yt-dlp priority / default | highest, default | 2nd | 3rd (needs explicit enable) |
| Signing | Deno-signed hardened runtime | ad hoc here | ad hoc |
| Needs network/perm flags | uses `--no-prompt` etc., sandboxed | no | no, pure interpreter |

Recommendation: **quickjs-ng** as the default bundled runtime. It is 25 MB smaller to ship (about 38 MB of
compressed payload) and trivially signable, and its 2.4 s extra per YouTube video extraction is small against
a typical download. Deno is the right choice if per-video latency matters more than download size: it is
2x faster and is yt-dlp's reference runtime (best tested path). Because yt-dlp accepts several runtimes,
it is possible to bundle qjs and let a power user's deno/node on PATH override it, but note
that deno outranks quickjs in the priority order, so a user-installed deno would win automatically
only if you also enable it. Reject node: no advantage over deno in speed and the largest binary.
Watch for a risk: yt-dlp's quickjs path has been the least exercised; pin `yt-dlp-ejs` and `yt-dlp` and
re-run the probe in CI on every bump. YouTube changes break extraction often, so ship a way to update
yt-dlp (the app needs an update channel anyway).

### Go/no-go budget

- GO for a single-binary CLI (quickjs-ng): **about 26 MB onefile**, **about 47 MB onedir**; or deno: 63 MB / 123 MB.
- Startup budget: onedir **0.11 s** `--help`, **about 0.14 s** to first yt-dlp call, and about 4.8 s total for a full
  qjs probe (2.5 s with deno). Onefile adds about 1.3 s of extraction per launch: acceptable for a CLI that
  is run once per download, bad for a GUI that spawns it repeatedly.
- Choose: ship a signed `.app`/`.pkg` containing an **onedir** layout (or a launcher that unpacks once into
  `~/Library/Application Support/Xtractor/<version>/` or `~/Library/Caches`, keyed by version hash), with
  quickjs-ng and the custom LGPL ffmpeg beside it.
- A launcher that unpacks the PyInstaller onefile once into a version-keyed directory avoids both the per-run
  extraction and the need to ship a bundle, at the cost of first-run latency of about 5 s (the first onefile
  run measured 5.5 s).

## 5. Gotchas checklist

1. Pass `path` for the bundled JS runtime on macOS. Auto-discovery of an exe next to the frozen binary is Windows only.
2. Set `remote_components` to `[]` and rely on the `yt-dlp-ejs` package, so there are no network fetches of JS.
3. `--collect-all yt_dlp_ejs` is mandatory, otherwise the solver scripts are missing.
4. A runtime that fails to execute (quarantine, missing exec bit, unsigned inside a hardened app) makes yt-dlp silently
   fall back to the no-JS format set: 43 formats and no `140`/`251`. Log `-v` output and assert on the
   "JS Challenge Providers" line in a smoke test, and on `140` being in the format list.
5. Use `quiet`/`no_warnings` carefully: the "Unknown codec iamf.001.001.Opus" warning is harmless.
6. Onefile ignores the extraction cost on each launch. Prefer onedir or a one-time cache.
7. Homebrew ffmpeg is GPL and dynamic. Never copy it; use the static LGPL build.
8. Brew's `libmp3lame.a` drags in `libmpg123`; build LAME from source with `--disable-decoder`.
9. Add `matroska_audio` muxer for `.mka`, and `mp4`+`ipod` for `.m4a`.
10. Quarantine on an unsigned binary blocks exec: sign and notarize, or distribute through a channel without quarantine.

## 6. Artifacts (scratch, not in repo)

`/private/tmp/claude-501/-Users-gerry-develop-Xtractor/3cb84c58-c938-4183-87c7-730be5683657/scratchpad/spike/`:
`venv/`, `probe.py`, `xprobe.py`, `fftest.sh`, `rt/{deno,node,qjs}`, `bin/{ffmpeg,ffprobe}`,
`ffbuild/configure.sh`, `dist_qjs/`, `dist_deno/`. A leftover cache dir `~/Library/Caches/Xtractor-spike/` holds a deno
and an ffmpeg copy (about 87 MB) from the cache-extract test.
