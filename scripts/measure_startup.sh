#!/usr/bin/env bash
# Measure size and start-up of the built binary and compare with the spec budgets.
#
#   scripts/measure_startup.sh [path/to/Xtractor]      (default dist/Xtractor)
#
# Env: RUNS (default 10) cold and warm runs; ENFORCE=1 exits non-zero on any budget breach;
#      JS_RUNTIME_LABEL (quickjs-ng|deno) picks the size budget (70 MB / 120 MB, spec section 6).
#
# "Cold" here = the first launch of a FRESH COPY of the binary (new inode, never executed
# before: includes macOS's first-exec checks). A true purged-disk-cache cold start needs
# `sudo purge`, which this script never runs; the numbers are therefore a proxy.
# "Warm" = repeated launches of the same file. Extraction is measured by running a command
# that extracts the tools and then fails immediately at the network (dead proxy) against an
# empty cache, minus the same command against a populated cache (median of RUNS).
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

BIN="${1:-$REPO_ROOT/dist/Xtractor}"
[ -x "$BIN" ] || die "binary not found: $BIN"
RUNS="${RUNS:-10}"
LABEL="${JS_RUNTIME_LABEL:-$(sed -n 's/.*"runtime": "\(.*\)".*/\1/p' "$BUILD_DIR/BUILDINFO-js.json" 2>/dev/null || echo quickjs-ng)}"
PYTHON="${PYTHON:-python3}"

exec "$PYTHON" - "$BIN" "$RUNS" "$LABEL" "${ENFORCE:-0}" <<'PY'
import os, shutil, statistics, subprocess, sys, tempfile, time

binary, runs, label, enforce = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4] == "1"
BUDGET = {"cold": 1.5, "warm": 0.5, "size_mb": 70.0 if label.startswith("quickjs") else 120.0}
work = tempfile.mkdtemp(prefix="xtractor-measure.")
cache = os.path.join(work, "cache")
env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
       "XTRACTOR_CACHE_DIR": cache}

def run(path, *args, e=None):
    t = time.perf_counter()
    r = subprocess.run([path, *args], env=e or env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    return time.perf_counter() - t, r.returncode

def stats(xs):
    return f"median {statistics.median(xs):.2f}s  min {min(xs):.2f}s  max {max(xs):.2f}s"

results, breaches = {}, []
size_mb = os.path.getsize(binary) / 1e6
print(f"binary: {binary}\nsize  : {size_mb:.1f} MB (budget <= {BUDGET['size_mb']:.0f} MB for {label})\n")
if size_mb > BUDGET["size_mb"]:
    breaches.append(f"size {size_mb:.1f} MB > {BUDGET['size_mb']} MB")

for arg in ("-h", "--version"):
    cold = []
    for i in range(runs):
        copy = os.path.join(work, f"X{i}")
        shutil.copyfile(binary, copy); os.chmod(copy, 0o755)
        subprocess.run(["codesign", "--force", "--sign", "-", copy], capture_output=True, check=False)
        t, rc = run(copy, arg); assert rc == 0, (arg, rc)
        cold.append(t); os.remove(copy)
    run(binary, arg)  # settle
    warm = [run(binary, arg)[0] for _ in range(runs)]
    results[arg] = (cold, warm)
    print(f"{arg:10s} cold(first launch of a fresh copy) {stats(cold)}\n{'':10s} warm                               {stats(warm)}")
    if statistics.median(cold) > BUDGET["cold"]:
        breaches.append(f"{arg} cold median {statistics.median(cold):.2f}s > {BUDGET['cold']}s")
    if statistics.median(warm) > BUDGET["warm"]:
        breaches.append(f"{arg} warm median {statistics.median(warm):.2f}s > {BUDGET['warm']}s")

# One-time tool extraction: command that extracts, then dies at the (dead) proxy.
dead = dict(env, https_proxy="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
url = "https://www.youtube.com/watch?v=SkVqJ1SGeL0"
n = max(3, runs // 2)
empty, full = [], []
for _ in range(n):
    shutil.rmtree(cache, ignore_errors=True)
    empty.append(run(binary, "-a", "-q", "-o", work, url, e=dead)[0])
    full.append(run(binary, "-a", "-q", "-o", work, url, e=dead)[0])
extract = statistics.median(empty) - statistics.median(full)
print(f"\ntool extraction (ffmpeg + JS runtime -> cache, {n} runs): empty-cache {stats(empty)}\n"
      f"{'':10s}populated-cache {stats(full)}\n{'':10s}=> one-time extraction cost about {extract:.2f}s")
shutil.rmtree(work, ignore_errors=True)

print("\nbudget check (spec section 6: cold <= 1.5s, warm <= 0.5s, size <= 70/120 MB)")
for b in breaches:
    print(f"  BREACH: {b}")
if not breaches:
    print("  all budgets met")
sys.exit(1 if (breaches and enforce) else 0)
PY
