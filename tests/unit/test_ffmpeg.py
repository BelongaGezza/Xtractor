from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.fixtures import AAC_441, OPUS, standard_formats
from xtractor import ffmpeg
from xtractor.errors import FileSystemError, InternalError, MissingDependency
from xtractor.formats import Tags, select_audio
from xtractor.options import AudioOptions

TAGS = Tags(title="Hello; rm -rf ~ #", artist="Chan", date="2024-01-31", url="https://u")


def argv_for(fmt: str, rate: int, br: str | None = None, *, tags: Tags = TAGS) -> list[str]:
    opts = AudioOptions(rate, fmt, br)  # type: ignore[arg-type]
    plan = select_audio(standard_formats(), opts)
    return ffmpeg.build_audio_argv(
        Path("/t/src.m4a"), Path("/t/out.tmp." + plan.ext), plan, opts, tags
    )


HEAD = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", "/t/src.m4a"]
MAP = ["-vn", "-map", "0:a:0", "-map_metadata", "-1"]
META = [
    "-metadata",
    "title=Hello; rm -rf ~ #",
    "-metadata",
    "artist=Chan",
    "-metadata",
    "date=2024-01-31",
    "-metadata",
    "comment=https://u",
]


def test_argv_default_copy() -> None:
    assert argv_for("m4a", 44100) == [
        *HEAD, *MAP, "-c:a", "copy", "-movflags", "+faststart", *META, "/t/out.tmp.m4a"
    ]  # fmt: skip


def test_argv_transcodes() -> None:
    assert argv_for("m4a", 44100, "192k")[len(HEAD) + len(MAP) :][:6] == [
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100"
    ]  # fmt: skip
    mp3 = argv_for("mp3", 44100)
    assert mp3[len(HEAD) + len(MAP) :][:8] == [
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-id3v2_version",
        "3",
    ]
    assert argv_for("wav", 48000)[-1] == "/t/out.tmp.wav"
    assert "pcm_s16le" in argv_for("wav", 48000)
    assert "libopus" in argv_for("opus", 48000, "96k")
    assert "flac" in argv_for("flac", 44100)


def test_argv_has_only_strings_and_no_shell_tricks() -> None:
    for argv in (argv_for("m4a", 44100), argv_for("mp3", 44100)):
        assert all(isinstance(a, str) for a in argv)
        assert "-metadata" in argv and "title=Hello; rm -rf ~ #" in argv  # one element


def test_argv_skips_empty_tags() -> None:
    argv = argv_for("m4a", 44100, tags=Tags())
    assert "-metadata" not in argv


def test_ffmpeg_bin_override() -> None:
    plan = select_audio([AAC_441], AudioOptions(44100, "m4a", None))
    argv = ffmpeg.build_audio_argv(
        Path("a"),
        Path("b"),
        plan,
        AudioOptions(44100, "m4a", None),
        Tags(),
        ffmpeg_bin=Path("/x/ffmpeg"),
    )
    assert argv[0] == "/x/ffmpeg"


# ------------------------------------------------------------ location
def test_locate_prefers_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ffmpeg, "_bundled_ffmpeg", lambda: Path("/never"))
    assert ffmpeg.locate_ffmpeg() == fake


def test_locate_falls_back_to_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    bundled = tmp_path / "ffmpeg"
    bundled.write_text("x")
    monkeypatch.setattr(ffmpeg, "_bundled_ffmpeg", lambda: bundled)
    assert ffmpeg.locate_ffmpeg() == bundled
    monkeypatch.setattr(ffmpeg, "_bundled_ffmpeg", lambda: None)
    with pytest.raises(MissingDependency) as info:
        ffmpeg.locate_ffmpeg()
    assert info.value.exit_code == 5


def test_run_ffmpeg_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(MissingDependency):
        ffmpeg.run_ffmpeg(["/definitely/not/ffmpeg"])
    with pytest.raises(InternalError, match="exit 1"):
        ffmpeg.run_ffmpeg(["/bin/sh", "-c", "echo bad >&2; exit 1"])
    ffmpeg.run_ffmpeg(["/bin/sh", "-c", "exit 0"], verbose=True)


def test_run_ffmpeg_maps_encoder_and_disk_errors() -> None:
    with pytest.raises(MissingDependency):
        ffmpeg.run_ffmpeg(["/bin/sh", "-c", "echo 'Unknown encoder libopus' >&2; exit 1"])
    with pytest.raises(FileSystemError):
        ffmpeg.run_ffmpeg(["/bin/sh", "-c", "echo 'No space left on device' >&2; exit 1"])


def test_run_never_uses_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    real = subprocess.run

    def spy(args: object, **kw: object) -> object:
        seen["args"], seen["kw"] = args, kw
        return real(["/bin/sh", "-c", "exit 0"], **kw)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", spy)
    ffmpeg.run_ffmpeg(["ffmpeg", "x; y"])
    assert isinstance(seen["args"], list)
    assert not seen["kw"].get("shell")  # type: ignore[attr-defined]


# ------------------------------------------------------------ real ffmpeg
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def probe(path: Path) -> dict[str, object]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)  # type: ignore[no-any-return]


def make_source(tmp_path: Path, rate: int, codec: str, name: str) -> Path:
    src = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:sample_rate={rate}:duration=1", "-c:a", codec, str(src)],
        check=True,
    )  # fmt: skip
    return src


def run_case(tmp_path: Path, src: Path, fmt: str, rate: int, fid_formats: list, br: str | None):  # type: ignore[no-untyped-def]
    opts = AudioOptions(rate, fmt, br)  # type: ignore[arg-type]
    plan = select_audio(fid_formats, opts)
    dst = tmp_path / f"out.tmp.{plan.ext}"
    ffmpeg.run_ffmpeg(ffmpeg.build_audio_argv(src, dst, plan, opts, TAGS))
    return plan, probe(dst)


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_real_default_path_is_stream_copy(tmp_path: Path) -> None:
    src = make_source(tmp_path, 44100, "aac", "src.m4a")
    plan, info = run_case(tmp_path, src, "m4a", 44100, [AAC_441], None)
    assert plan.copy
    stream = info["streams"][0]  # type: ignore[index]
    assert stream["codec_name"] == "aac" and stream["sample_rate"] == "44100"
    tags = info["format"]["tags"]  # type: ignore[index]
    assert tags["title"] == "Hello; rm -rf ~ #" and tags["artist"] == "Chan"

    def md5(p: Path) -> str:
        return subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(p), "-map", "0:a:0", "-c",
                "copy",
                "-f", "md5", "-",
            ],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip

    assert md5(src) == md5(tmp_path / "out.tmp.m4a")


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_real_wav_48k_and_mp3_and_opus(tmp_path: Path) -> None:
    src = make_source(tmp_path, 48000, "libopus", "src.webm")
    _, info = run_case(tmp_path, src, "wav", 48000, [OPUS], None)
    s = info["streams"][0]  # type: ignore[index]
    assert (s["codec_name"], s["sample_rate"]) == ("pcm_s16le", "48000")
    _, info = run_case(tmp_path, src, "mp3", 44100, [OPUS], "192k")
    s = info["streams"][0]  # type: ignore[index]
    assert (s["codec_name"], s["sample_rate"]) == ("mp3", "44100")
    plan, info = run_case(tmp_path, src, "opus", 48000, [OPUS], None)
    assert plan.copy
    assert info["streams"][0]["codec_name"] == "opus"  # type: ignore[index]
    _, info = run_case(tmp_path, src, "m4a", 44100, [OPUS], None)
    s = info["streams"][0]  # type: ignore[index]
    assert (s["codec_name"], s["sample_rate"]) == ("aac", "44100")
    _, info = run_case(tmp_path, src, "flac", 48000, [OPUS], None)
    assert info["streams"][0]["codec_name"] == "flac"  # type: ignore[index]
