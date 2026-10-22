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
# "Warm" = repeated launches of the same file. Tool extraction is measured by timing the
# extraction code (bundle.py) on the staged bundle against an empty cache (median of RUNS/2).
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

BIN="${1:-$REPO_ROOT/dist/Xtractor}"
[ -x "$BIN" ] || die "binary not found: $BIN"
RUNS="${RUNS:-10}"
LABEL="${JS_RUNTIME_LABEL:-$(sed -n 's/.*"runtime": "\(.*\)".*/\1/p' "$BUILD_DIR/BUILDINFO-js.json" 2>/dev/null || echo quickjs-ng)}"
PYTHON="${PYTHON:-python3}"
export BUILD_DIR REPO_PYTHON="$REPO_ROOT/.venv/bin/python" REPO_SRC="$REPO_ROOT/src"

exec "$PYTHON" - "$BIN" "$RUNS" "$LABEL" "${ENFORCE:-0}" <<'PY'
import os, shutil, statistics, subprocess, sys, tempfile, time

binary, runs, label, enforce = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4] == "1"
BUDGET = {"cold": 1.5, "warm": 0.5, "size_mb": 70.0 if label.startswith("quickjs") else 120.0}
work = tempfile.mkdtemp(prefix="xtractor-measure.")
cache = os.path.join(work, "cache")
env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
       "XTRACTOR_CACHE_DIR": cache, "XTRACTOR_ALLOW_OVERRIDES": "1"}

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

# One-time tool extraction. An end-to-end comparison (empty vs populated cache) is lost in
# the noise of network retries, so time the extraction code itself on the staged bundle.
stage = os.path.join(os.environ["BUILD_DIR"], "stage", "xtractor_bundle")
probe = (
    "import time; from xtractor import bundle; t=time.perf_counter();"
    "bundle.bundled_asset_path('ffmpeg'); bundle.bundled_js(); a=time.perf_counter()-t;"
    "t=time.perf_counter(); bundle.bundled_asset_path('ffmpeg'); bundle.bundled_js();"
    "print(a, time.perf_counter()-t)"
)
if os.path.isfile(os.path.join(stage, "manifest.json")):
    first, reuse = [], []
    for _ in range(max(3, runs // 2)):
        shutil.rmtree(cache, ignore_errors=True)
        out = subprocess.run([os.environ["REPO_PYTHON"], "-c", probe], capture_output=True, text=True,
                             env=dict(env, XTRACTOR_BUNDLE_DIR=stage, PYTHONPATH=os.environ["REPO_SRC"]),
                             check=False).stdout.split()
        first.append(float(out[0])); reuse.append(float(out[1]))
    print(f"\ntool extraction (ffmpeg + JS runtime -> empty cache, write + SHA-256): {stats(first)}\n"
          f"{'':10s}later starts (verify hash of the existing files): {stats(reuse)}")
else:
    print("\n(tool extraction not measured: run scripts/build_binary.sh first to create build/stage)")
shutil.rmtree(work, ignore_errors=True)

print("\nbudget check (spec section 6: cold <= 1.5s, warm <= 0.5s, size <= 70/120 MB)")
for b in breaches:
    print(f"  BREACH: {b}")
if not breaches:
    print("  all budgets met")
sys.exit(1 if (breaches and enforce) else 0)
PY
