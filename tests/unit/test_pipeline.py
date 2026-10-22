from __future__ import annotations

import errno
from pathlib import Path

import pytest

from tests.unit.fakes import FakeExtractor, FakeFfmpeg, info_with, make_deps
from tests.unit.fixtures import AAC_441, AVC, OPUS, VP9, standard_formats
from xtractor.cli import parse_args
from xtractor.errors import (
    FileSystemError,
    FormatUnavailable,
    InternalError,
    MissingDependency,
    NetworkError,
    VideoUnavailable,
)
from xtractor.formats import FormatInfo
from xtractor.pipeline import format_table, list_formats, run

URL = "https://youtu.be/dQw4w9WgXcQ"


def opts(tmp_path: Path, *args: str):  # type: ignore[no-untyped-def]
    return parse_args([*args, "-o", str(tmp_path / "out"), URL])


def listing(d: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) for p in d.rglob("*"))


def test_audio_copy_path(tmp_path: Path) -> None:
    ff = FakeFfmpeg()
    ex = FakeExtractor()
    deps, err = make_deps(ex, ff)
    final = run(opts(tmp_path, "-a"), deps)
    assert final == tmp_path / "out" / "My Title.m4a"
    assert final.read_bytes() == b"converted"
    assert ex.downloads[0][0] == "140"
    assert ex.downloads[0][3] is None
    argv = ff.calls[0]
    assert "copy" in argv and "title=My: Title/?" in argv
    assert "comment=https://www.youtube.com/watch?v=dQw4w9WgXcQ" in argv
    assert listing(tmp_path) == ["out", "out/My Title.m4a"]  # temp dir is gone
    assert "Copying audio stream" in err.getvalue()


def test_audio_wav_transcode_notice(tmp_path: Path) -> None:
    ff = FakeFfmpeg()
    deps, err = make_deps(FakeExtractor(), ff)
    final = run(opts(tmp_path, "-a", "--audio-format", "wav", "--sample-rate", "32000"), deps)
    assert final.suffix == ".wav"
    assert "pcm_s16le" in ff.calls[0]
    assert "resampling 48000 Hz -> 32000 Hz" in err.getvalue()


def test_video_selection_and_merge(tmp_path: Path) -> None:
    ex = FakeExtractor()
    deps, _ = make_deps(ex)
    final = run(opts(tmp_path, "-v", "--resolution", "720"), deps)
    assert ex.downloads[0][0] == "avc720+140"
    assert ex.downloads[0][3] == "mp4"
    assert final.name == "My Title.mp4"
    assert final.exists()
    assert listing(tmp_path) == ["out", "out/My Title.mp4"]


def test_video_container_switch_notice(tmp_path: Path) -> None:
    ex = FakeExtractor()
    deps, err = make_deps(ex)
    final = run(opts(tmp_path, "-v", "--resolution", "2160"), deps)
    assert final.suffix == ".mkv"
    assert ex.downloads[0][3] == "mkv"
    assert "container switched mp4 -> mkv" in err.getvalue()


def test_video_strict_exits_6_and_writes_nothing(tmp_path: Path) -> None:
    deps, _ = make_deps()
    with pytest.raises(FormatUnavailable):
        run(opts(tmp_path, "-v", "--resolution", "2160", "--strict-format"), deps)
    assert listing(tmp_path) == []  # not even the output directory was created


def test_quiet_suppresses_notices(tmp_path: Path) -> None:
    deps, err = make_deps(quiet=True)
    run(opts(tmp_path, "-v", "--resolution", "2160"), deps)
    assert err.getvalue() == ""


def test_template_fields_and_resolution(tmp_path: Path) -> None:
    deps, _ = make_deps()
    o = parse_args(
        [
            "-v",
            "--resolution",
            "720",
            "-n",
            "%(id)s_%(resolution)s_%(uploader)s",
            URL,
            "-o",
            str(tmp_path),
        ]
    )
    assert run(o, deps).name == "dQw4w9WgXcQ_720p_Chan.mp4"


def test_existing_file_is_skipped(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "My Title.m4a"
    existing.write_bytes(b"old")
    ex = FakeExtractor()
    deps, err = make_deps(ex)
    assert run(opts(tmp_path, "-a"), deps) == existing
    assert existing.read_bytes() == b"old"
    assert ex.downloads == []
    assert "exists, skipping" in err.getvalue()


def test_overwrite_replaces(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "My Title.m4a").write_bytes(b"old")
    deps, _ = make_deps()
    final = run(opts(tmp_path, "-a", "--overwrite"), deps)
    assert final.read_bytes() == b"converted"
    assert listing(out) == ["My Title.m4a"]


def test_output_file_path(tmp_path: Path) -> None:
    deps, _ = make_deps()
    target = tmp_path / "x" / "y" / "song.m4a"
    o = parse_args(["-a", "-o", str(target), URL])
    assert run(o, deps) == target
    assert target.exists()


@pytest.mark.parametrize(
    "exc",
    [
        KeyboardInterrupt(),
        NetworkError("network error"),
        OSError(errno.ENOSPC, "No space left on device"),
    ],
)
def test_failure_mid_download_leaves_no_trace(tmp_path: Path, exc: BaseException) -> None:
    def boom(_: Path) -> None:
        raise exc

    deps, _ = make_deps(FakeExtractor(on_download=boom))
    with pytest.raises(type(exc)):
        run(opts(tmp_path, "-a"), deps)
    assert listing(tmp_path) == []


def test_failure_keeps_preexisting_directory_and_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    deps, _ = make_deps(FakeExtractor(fail_probe=NetworkError("x")))
    with pytest.raises(NetworkError):
        run(opts(tmp_path, "-a"), deps)
    assert listing(out) == ["keep.txt"]


def test_ffmpeg_failure_cleans_up(tmp_path: Path) -> None:
    deps, _ = make_deps(ffmpeg=FakeFfmpeg(fail=InternalError("ffmpeg failed")))
    with pytest.raises(InternalError):
        run(opts(tmp_path, "-a"), deps)
    assert listing(tmp_path) == []


def test_missing_encoder_error_propagates(tmp_path: Path) -> None:
    deps, _ = make_deps(ffmpeg=FakeFfmpeg(fail=MissingDependency("no encoder")))
    with pytest.raises(MissingDependency):
        run(opts(tmp_path, "-a", "--audio-format", "mp3"), deps)


def test_wrong_extension_from_downloader_is_internal_error(tmp_path: Path) -> None:
    class Odd(FakeExtractor):
        def download(self, ref, *a, **k):  # type: ignore[no-untyped-def]
            p = super().download(ref, *a, **k)
            q = p.with_suffix(".webm")
            p.rename(q)
            return q

    deps, _ = make_deps(Odd())
    with pytest.raises(InternalError, match="expected"):
        run(opts(tmp_path, "-v"), deps)
    assert listing(tmp_path) == []


# ------------------------------------------------------------ DRM / live (T5.3)
@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"is_live": True, "live_status": "is_live"}, "live"),
        ({"live_status": "is_upcoming"}, "live"),
        ({"live_status": "post_live"}, "live"),
    ],
)
def test_live_rejected(tmp_path: Path, kw: dict[str, object], reason: str) -> None:
    ex = FakeExtractor(info_with(standard_formats(), **kw))
    deps, _ = make_deps(ex)
    with pytest.raises(VideoUnavailable, match=reason):
        run(opts(tmp_path, "-a"), deps)
    assert ex.downloads == []
    assert listing(tmp_path) == []


def test_all_drm_rejected(tmp_path: Path) -> None:
    drm = [FormatInfo(**{**f.__dict__, "has_drm": True}) for f in (AAC_441, OPUS, AVC[720])]
    ex = FakeExtractor(info_with(drm))
    deps, _ = make_deps(ex)
    with pytest.raises(VideoUnavailable, match="DRM"):
        run(opts(tmp_path, "-v"), deps)
    assert ex.downloads == [] and listing(tmp_path) == []


# ------------------------------------------------------------ --list-formats (T5.2)
def test_format_table_snapshot() -> None:
    fmts = [
        FormatInfo("sb0", "mhtml"),
        AAC_441,
        FormatInfo(
            "137", "mp4", "avc1.640028", height=1080, fps=24, filesize=5 * 1024 * 1024, note="1080p"
        ),
        FormatInfo("x", "mp4", "avc1.4d", "mp4a.40.2", height=360, has_drm=True, note="medium"),
        VP9[1080],
    ]
    table = format_table(info_with(fmts)).splitlines()
    assert table[0].split() == [
        "ID", "EXT", "RES", "FPS", "VCODEC", "ACODEC", "RATE", "SIZE", "NOTES",
    ]  # fmt: skip
    body = "\n".join(table[1:])
    assert "sb0" not in body
    assert "140" in table[1] and "audio only" in table[1] and "44100" in table[1]
    assert "1080p" in table[2] and "24" in table[2] and "5.0 MiB" in table[2]
    assert "video only" in table[2] and table[2].count("1080p") == 1
    assert "DRM" in table[3] and "medium" in table[3]
    assert len(table) == 5


def test_list_formats_uses_probe_only(tmp_path: Path) -> None:
    ex = FakeExtractor()
    deps, _ = make_deps(ex)
    o = parse_args(["--list-formats", URL])
    text = list_formats(o, deps)
    assert text.startswith("ID")
    assert ex.downloads == [] and len(ex.probes) == 1


def test_fs_error_class() -> None:
    from xtractor.errors import classify_exception

    err = classify_exception(OSError(errno.EACCES, "Permission denied", "/x"))
    assert isinstance(err, FileSystemError)
