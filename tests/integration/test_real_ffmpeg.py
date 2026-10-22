"""Real ffmpeg/ffprobe tests (T4.4): run the pipeline's ffmpeg step on synthetic audio."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit.fakes import FakeExtractor, info_with, make_deps
from tests.unit.fixtures import AAC_441, standard_formats
from xtractor.cli import parse_args
from xtractor.ffmpeg import run_ffmpeg
from xtractor.pipeline import run

pytestmark = [
    pytest.mark.ffmpeg,
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
        reason="ffmpeg/ffprobe not installed",
    ),
]

URL = "https://youtu.be/dQw4w9WgXcQ"


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)  # type: ignore[no-any-return]


def stream_md5(path: Path) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip()


@pytest.fixture(scope="module")
def aac_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    src = tmp_path_factory.mktemp("src") / "dQw4w9WgXcQ.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "2", "-c:a", "aac", str(src)],
        check=True,
    )  # fmt: skip
    return src


class CopyingExtractor(FakeExtractor):
    def __init__(self, source: Path) -> None:
        super().__init__(info_with(standard_formats()))
        self.source = source

    def download(self, ref, fmt, dest_dir, outtmpl, merge_to, on_progress):  # type: ignore[no-untyped-def]
        path = dest_dir / f"{ref.video_id}.m4a"
        shutil.copy(self.source, path)
        return path


def pipeline_run(tmp_path: Path, source: Path, *args: str) -> Path:
    deps, _ = make_deps(CopyingExtractor(source))
    deps.run_ffmpeg = lambda argv: run_ffmpeg(argv)
    return run(parse_args([*args, "-o", str(tmp_path), URL]), deps)


def test_default_audio_is_stream_copy_44k(tmp_path: Path, aac_source: Path) -> None:
    final = pipeline_run(tmp_path, aac_source, "-a")
    s = probe(final)["streams"][0]
    assert (s["codec_name"], s["sample_rate"]) == ("aac", "44100")
    assert "m4a" in probe(final)["format"]["format_name"]
    assert stream_md5(final) == stream_md5(aac_source)  # packets copied, not re-encoded
    tags = {k.lower(): v for k, v in probe(final)["format"]["tags"].items()}
    assert tags["title"] == "My: Title/?" and tags["artist"] == "Chan"
    assert tags["comment"].endswith("dQw4w9WgXcQ")
    assert AAC_441.format_id == "140"


def test_wav_48k(tmp_path: Path, aac_source: Path) -> None:
    final = pipeline_run(
        tmp_path, aac_source, "-a", "--audio-format", "wav", "--sample-rate", "48000"
    )
    s = probe(final)["streams"][0]
    assert (s["codec_name"], s["sample_rate"]) == ("pcm_s16le", "48000")


@pytest.mark.parametrize(
    ("fmt", "codec", "rate"),
    [("mp3", "mp3", "48000"), ("flac", "flac", "44100"), ("m4a", "aac", "48000")],
)
def test_other_targets(tmp_path: Path, aac_source: Path, fmt: str, codec: str, rate: str) -> None:
    args = ["-a", "--audio-format", fmt, "--sample-rate", rate]
    final = pipeline_run(tmp_path, aac_source, *args)
    s = probe(final)["streams"][0]
    assert (s["codec_name"], s["sample_rate"]) == (codec, rate)


def test_bitrate_override_forces_transcode(tmp_path: Path, aac_source: Path) -> None:
    final = pipeline_run(tmp_path, aac_source, "-a", "--audio-quality", "96k")
    assert stream_md5(final) != stream_md5(aac_source)
    assert probe(final)["streams"][0]["codec_name"] == "aac"
