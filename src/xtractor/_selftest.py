"""Offline self-test of a built binary: ``XTRACTOR_SELFTEST=1 Xtractor --xtractor-selftest``.

Used by the release workflow (no network). It extracts the embedded tools, checks the
ffmpeg build is LGPL and can encode/decode every format Xtractor produces (a generated WAV is
transcoded to m4a, opus, flac, mp3, wav and an mkv remux, then each is decoded), runs the
embedded JavaScript runtime, and imports ``yt_dlp_ejs``. It only runs executables that normal
operation already runs, takes no input, and is inert unless the environment variable is set.
"""

from __future__ import annotations

import importlib
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from . import bundle

ENV = "XTRACTOR_SELFTEST"
FLAG = "--xtractor-selftest"


def _tone(path: Path) -> None:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = b"".join(
            struct.pack("<hh", s, s)
            for s in (int(8000 * math.sin(2 * math.pi * 440 * i / 44100)) for i in range(44100))
        )
        w.writeframes(frames)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=120
    )


def run() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "ok  " if ok else "FAIL"
        print(f"{status} {name}" + (f": {detail}" if detail and not ok else ""))  # stdout-ok
        if not ok:
            failures.append(name)

    ff = bundle.bundled_asset_path("ffmpeg")
    check("embedded ffmpeg extracted", ff is not None and ff.exists())
    if ff is not None:
        info = _run([str(ff), "-hide_banner", "-version"]).stdout
        check(
            "ffmpeg is LGPL (no gpl/nonfree/version3)",
            not any(f in info for f in ("--enable-gpl", "--enable-nonfree", "--enable-version3")),
        )
        with tempfile.TemporaryDirectory(prefix="xtractor-selftest-") as tmp:
            d = Path(tmp)
            _tone(d / "in.wav")
            base = [str(ff), "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            wl = ["-protocol_whitelist", "file,pipe"]
            for out, codec in (
                ("a.m4a", ["-c:a", "aac"]),
                ("a.opus", ["-c:a", "libopus"]),
                ("a.flac", ["-c:a", "flac"]),
                ("a.mp3", ["-c:a", "libmp3lame"]),
                ("a.wav", ["-c:a", "pcm_s16le", "-ar", "48000"]),
            ):
                r = _run([*base, *wl, "-i", str(d / "in.wav"), *codec, str(d / out)])
                check(f"encode {out}", r.returncode == 0, r.stderr.strip()[-200:])
                r = _run([*base, *wl, "-i", str(d / out), "-f", "null", "-"])
                check(f"decode {out}", r.returncode == 0, r.stderr.strip()[-200:])
            r = _run([*base, *wl, "-i", str(d / "a.m4a"), "-c", "copy", str(d / "a.mkv")])
            check("remux m4a -> mkv", r.returncode == 0, r.stderr.strip()[-200:])
    js = bundle.bundled_js()
    check("embedded JS runtime extracted", js is not None)
    if js is not None:
        name, path = js
        argv = (
            [str(path), "eval", "console.log(6*7)"]
            if name == "deno"
            else [str(path), "-e", "console.log(6*7)"]
        )
        r = _run(argv)
        check(f"{name} runs JavaScript", r.stdout.strip() == "42", (r.stdout + r.stderr)[-200:])
    try:
        importlib.import_module("yt_dlp_ejs")

        check("yt_dlp_ejs importable", True)
    except ImportError as exc:
        check("yt_dlp_ejs importable", False, str(exc))
    print("selftest:", "FAILED" if failures else "passed", file=sys.stderr)
    return 1 if failures else 0
