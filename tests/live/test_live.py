"""Opt-in live smoke tests (AC3, AC4, AC6, AC7 + --list-formats). Run with:

XTRACTOR_LIVE=1 pytest -m live
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.live.urls import TITLE_STEM, URL
from xtractor.cli import main

pytestmark = pytest.mark.live

needs_tools = pytest.mark.skipif(
    shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
    reason="ffmpeg/ffprobe required",
)


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)  # type: ignore[no-any-return]


def run_main(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main([*args, URL])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


@needs_tools
def test_ac3_default_audio_is_m4a_44100_copied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_main(capsys, "-a", "-q", "-o", str(tmp_path))
    assert code == 0, err
    path = Path(out.strip())
    assert out.count("\n") == 1 and path.parent == tmp_path and path.name == f"{TITLE_STEM}.m4a"
    streams = probe(path)["streams"]
    assert [(s["codec_name"], s["sample_rate"]) for s in streams] == [("aac", "44100")]
    assert "mp4" in probe(path)["format"]["format_name"]
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no temp leftovers


@needs_tools
def test_ac4_wav_48k(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run_main(
        capsys, "-a", "-q", "--sample-rate", "48000", "--audio-format", "wav", "-o", str(tmp_path)
    )
    assert code == 0, err
    s = probe(Path(out.strip()))["streams"][0]
    assert (s["codec_name"], s["sample_rate"]) == ("pcm_s16le", "48000")


@needs_tools
def test_ac6_video_720(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run_main(capsys, "-v", "-q", "--resolution", "720", "-o", str(tmp_path))
    assert code == 0, err
    streams = probe(Path(out.strip()))["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert video["codec_name"] == "h264" and video["height"] <= 720
    assert audio["codec_name"] == "aac"


@needs_tools
def test_ac6_video_default_is_h264_aac_mp4_up_to_1080(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_main(capsys, "-v", "-q", "-o", str(tmp_path))
    assert code == 0, err
    path = Path(out.strip())
    assert path.suffix == ".mp4"
    video = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264" and video["height"] <= 1080


def test_list_formats_table(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run_main(capsys, "--list-formats")
    assert code == 0, err
    assert out.splitlines()[0].startswith("ID")
    assert "audio only" in out and "mp4a.40.2" in out and "avc1" in out


@needs_tools
def test_resolution_above_max_falls_back_with_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """This video tops out at 1080p, so AC7's container switch cannot be exercised live
    (it is covered with fixtures); a 2160 request must fall back to 1080p and say so."""
    code, out, err = run_main(
        capsys, "-v", "--resolution", "2160", "--strict-format", "-o", str(tmp_path)
    )
    assert code == 0, err
    assert "2160p unavailable" in err
    video = next(s for s in probe(Path(out.strip()))["streams"] if s["codec_type"] == "video")
    assert video["height"] == 1080
