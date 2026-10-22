#!/usr/bin/env bash
# Acceptance test of the built binary against ONE Creative Commons video:
# Blender "Caminandes 3: Llamigos" (CC-BY), YouTube id SkVqJ1SGeL0. Nothing else is downloaded.
#
#   scripts/accept_binary.sh [path/to/Xtractor]        (default dist/Xtractor)
#
# Every check runs with a scrubbed environment: PATH=/usr/bin:/bin, so no Homebrew ffmpeg,
# deno, node or Python can be picked up; only the embedded tools can work. ffprobe (from
# build/, built by build_ffmpeg.sh) is called by absolute path for verification only.
#
# Env: ACCEPT_DIR (work dir, default a fresh temp dir, deleted on exit), KEEP=1 to keep it,
#      FFPROBE (default build/ffprobe), XTRACTOR_CACHE_DIR (default: a fresh temp cache so the
#      first-run extraction is really exercised; set to reuse one).
set -uo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

BIN="${1:-$REPO_ROOT/dist/Xtractor}"
[ -x "$BIN" ] || die "binary not found: $BIN"
BIN="$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")"
FFPROBE="${FFPROBE:-$BUILD_DIR/ffprobe}"
[ -x "$FFPROBE" ] || die "ffprobe not found at $FFPROBE (run scripts/build_ffmpeg.sh)"
VIDEO_ID=SkVqJ1SGeL0
URL="https://www.youtube.com/watch?v=$VIDEO_ID"
WORK="${ACCEPT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/xtractor-accept.XXXXXX")}"
mkdir -p "$WORK"
CACHE="${XTRACTOR_CACHE_DIR:-$WORK/cache}"
cleanup() { [ "${KEEP:-0}" = 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); echo "  PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL  $*"; }
skip() { SKIP=$((SKIP+1)); echo "  SKIP  $*"; }
now()  { python3 -c 'import time; print(f"{time.time():.3f}")'; }

# run_x ARGS... : run the binary in the scrubbed environment; sets RC, OUT (stdout), ERR (stderr).
run_x() {
  env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="${TMPDIR:-/tmp}" XTRACTOR_CACHE_DIR="$CACHE" \
    "$BIN" "$@" >"$WORK/out.txt" 2>"$WORK/err.txt"
  RC=$?
  OUT="$(cat "$WORK/out.txt")"; ERR="$(cat "$WORK/err.txt")"
}
probe() { "$FFPROBE" -v error -show_entries "$1" -of default=nw=1 "$2" 2>&1; }
field() { probe "stream=$1" "$2" | sed -n "s/^$1=//p" | head -1; }

echo "binary : $BIN ($(stat -f %z "$BIN") bytes)"
echo "work   : $WORK"
echo "path   : /usr/bin:/bin (scrubbed)"
echo

echo "[1] -h"
run_x -h
{ [ $RC -eq 0 ] && grep -q -i "usage" <<<"$OUT" && grep -q -- "--list-formats" <<<"$OUT"; } \
  && ok "-h exits 0 and lists options" || bad "-h (rc=$RC)"

echo "[2] --version"
run_x --version
WANT="Xtractor $(app_version)"
[ $RC -eq 0 ] && [ "$OUT" = "$WANT" ] && ok "--version prints '$OUT'" || bad "--version: rc=$RC out='$OUT' want='$WANT'"

echo "[3] -a (default m4a, 44100 Hz, stream copy)"
mkdir -p "$WORK/a"
T0=$(now)
run_x -a --verbose -o "$WORK/a" "$URL"
T1=$(now)
AUDIO_FIRST_SECS=$(python3 -c "print(f'{$T1-$T0:.1f}')")
F="$(ls "$WORK"/a/*.m4a 2>/dev/null | head -1)"
if [ $RC -eq 0 ] && [ -n "$F" ]; then
  codec="$(field codec_name "$F")"; rate="$(field sample_rate "$F")"; fmt="$(probe format=format_name "$F")"
  [ "$codec" = aac ] && [ "$rate" = 44100 ] && ok "m4a aac $rate Hz ($fmt)" \
    || bad "m4a stream is codec=$codec rate=$rate (want aac 44100)"
  grep -q -- "-c:a copy" <<<"$ERR" && ok "ffmpeg ran with -c:a copy (stream copy, no re-encode)" \
    || bad "no '-c:a copy' in the ffmpeg command"
  grep -q "jsc:quickjs\|jsc:deno" <<<"$ERR" && ok "embedded JS runtime solved the YouTube challenge" \
    || bad "no JS challenge solving line in --verbose output"
  echo "        first run (tools extracted into an empty cache): ${AUDIO_FIRST_SECS}s"
else
  bad "-a failed rc=$RC: $(tail -3 <<<"$ERR")"
fi
ls "$CACHE"/*/ffmpeg >/dev/null 2>&1 && ok "ffmpeg extracted to cache: $(ls -d "$CACHE"/*)" || bad "no ffmpeg in $CACHE"
rm -rf "$WORK/a"; mkdir -p "$WORK/a"
T0=$(now); run_x -a -q -o "$WORK/a" "$URL"; T1=$(now)
AUDIO_WARM_SECS=$(python3 -c "print(f'{$T1-$T0:.1f}')")
[ $RC -eq 0 ] && echo "        full audio extraction, warm cache: ${AUDIO_WARM_SECS}s" || bad "second -a failed rc=$RC"

echo "[4] -a --sample-rate 48000 --audio-format wav"
mkdir -p "$WORK/w"
run_x -a --sample-rate 48000 --audio-format wav -o "$WORK/w" "$URL"
F="$(ls "$WORK"/w/*.wav 2>/dev/null | head -1)"
if [ $RC -eq 0 ] && [ -n "$F" ]; then
  codec="$(field codec_name "$F")"; rate="$(field sample_rate "$F")"
  [ "$codec" = pcm_s16le ] && [ "$rate" = 48000 ] && ok "wav $codec $rate Hz" || bad "wav is $codec $rate"
else bad "wav extraction failed rc=$RC: $(tail -3 <<<"$ERR")"; fi
rm -rf "$WORK/w"

echo "[5] -v --resolution 720"
mkdir -p "$WORK/v"
run_x -v --resolution 720 -o "$WORK/v" "$URL"
F="$(ls "$WORK"/v/*.mp4 "$WORK"/v/*.mkv 2>/dev/null | head -1)"
if [ $RC -eq 0 ] && [ -n "$F" ]; then
  h="$(field height "$F")"; types="$(probe stream=codec_type "$F" | tr '\n' ' ')"
  [ "$h" = 720 ] && ok "video height $h" || bad "video height is '$h'"
  grep -q "audio" <<<"$types" && grep -q "video" <<<"$types" && ok "video + audio streams merged by the embedded ffmpeg" \
    || bad "streams: $types"
else bad "-v failed rc=$RC: $(tail -3 <<<"$ERR")"; fi
rm -rf "$WORK/v"

echo "[5b] -v --resolution 1080 --video-format mkv"
mkdir -p "$WORK/m"
run_x -v --resolution 1080 --video-format mkv -o "$WORK/m" "$URL"
F="$(ls "$WORK"/m/*.mkv 2>/dev/null | head -1)"
if [ $RC -eq 0 ] && [ -n "$F" ]; then
  h="$(field height "$F")"; [ "$h" = 1080 ] && ok "mkv video height $h" || bad "mkv height is '$h'"
else bad "mkv failed rc=$RC: $(tail -3 <<<"$ERR")"; fi
rm -rf "$WORK/m"

echo "[6] --list-formats"
run_x --list-formats "$URL"
if [ $RC -eq 0 ] && grep -q -E '(^|[^0-9])(140|251)([^0-9]|$)' <<<"$OUT"; then
  ok "table lists $(wc -l <<<"$OUT" | tr -d ' ') lines incl. JS-gated audio ids (140/251)"
else bad "--list-formats rc=$RC (no 140/251: the JS runtime may not have worked)"; fi

echo "[7] Ctrl-C mid-download: exit 130, nothing left behind"
mkdir -p "$WORK/c"
TMPBEFORE="$(ls -d "${TMPDIR:-/tmp}"/_MEI* 2>/dev/null | wc -l | tr -d ' ')"
python3 - "$BIN" "$WORK/c" "$URL" "$CACHE" "$WORK/ctrlc.txt" <<'PY'
import os, signal, subprocess, sys, time
binary, out, url, cache, report = sys.argv[1:6]
env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
       "XTRACTOR_CACHE_DIR": cache}
p = subprocess.Popen([binary, "-v", "--resolution", "1080", "-o", out, url], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
def temp_bytes():
    total = 0
    for root, _dirs, files in os.walk(out):
        for f in files:
            try: total += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    return total
sent = False
deadline = time.time() + 120
while p.poll() is None and time.time() < deadline:
    if not sent and temp_bytes() > 300_000:  # a real download is under way
        os.killpg(p.pid, signal.SIGINT)      # what a terminal's Ctrl-C does
        sent = True
    time.sleep(0.02)
if p.poll() is None:
    os.killpg(p.pid, signal.SIGKILL); p.wait()
left = sorted(os.listdir(out))
open(report, "w").write(f"{p.returncode} {int(sent)} {' '.join(left)}\n")
PY
read -r RC_C SENT LEFT <"$WORK/ctrlc.txt" || true
LEFT="$(sed 's/^[0-9-]* [01] *//' "$WORK/ctrlc.txt")"
TMPAFTER="$(ls -d "${TMPDIR:-/tmp}"/_MEI* 2>/dev/null | wc -l | tr -d ' ')"
if [ "$SENT" != 1 ]; then
  skip "download finished before Ctrl-C could be sent (rc=$RC_C); rerun"
else
  [ "$RC_C" = 130 ] && ok "exit code 130" || bad "exit code $RC_C (want 130)"
  [ -z "$LEFT" ] && ok "no partial/temp files left in the output directory" || bad "left behind: $LEFT"
  [ "$TMPAFTER" -le "$TMPBEFORE" ] && ok "no leaked PyInstaller _MEI temp dir" || bad "_MEI dirs: $TMPBEFORE -> $TMPAFTER"
  if pgrep -f "$CACHE" >/dev/null 2>&1; then bad "orphan ffmpeg/qjs process still running"; else ok "no orphan child processes"; fi
fi

echo
echo "audio extraction (-a, m4a copy): first run ${AUDIO_FIRST_SECS:-?}s incl. one-time tool extraction, warm ${AUDIO_WARM_SECS:-?}s"
echo "result: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -eq 0 ]
