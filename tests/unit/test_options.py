from __future__ import annotations

from pathlib import Path

import pytest

from xtractor.cli import parse_args
from xtractor.errors import UsageError
from xtractor.options import Options

URL = "https://youtu.be/dQw4w9WgXcQ"


def parse(*args: str) -> Options:
    return parse_args(list(args))


def fails(*args: str) -> str:
    with pytest.raises(UsageError) as info:
        parse(*args)
    return str(info.value)


# AC2
def test_no_mode_and_both_modes() -> None:
    assert "-a/--audio or -v/--video" in fails(URL)
    assert "mutually exclusive" in fails("-a", "-v", URL)


def test_missing_url_and_bad_url() -> None:
    assert "URL is required" in fails("-a")
    assert "not a YouTube URL" in fails("-a", "https://vimeo.com/1")


def test_cross_mode_flags_name_the_offender() -> None:
    assert "--resolution" in fails("-a", "--resolution", "720", URL)
    assert "--video-format" in fails("-a", "--video-format", "mkv", URL)
    assert "--strict-format" in fails("-a", "--strict-format", URL)
    assert "--sample-rate" in fails("-v", "--sample-rate", "48000", URL)
    assert "--audio-format" in fails("-v", "--audio-format", "mp3", URL)
    assert "--audio-quality" in fails("-v", "--audio-quality", "192k", URL)


# AC5
def test_bad_sample_rate_lists_valid() -> None:
    msg = fails("-a", "--sample-rate", "12345", URL)
    for rate in ("22050", "32000", "44100", "48000", "88200", "96000"):
        assert rate in msg
    assert "--sample-rate" in fails("-a", "--sample-rate", "abc", URL)


def test_defaults_audio() -> None:
    o = parse("-a", URL)
    assert o.audio is not None
    assert (o.audio.sample_rate, o.audio.fmt, o.audio.bitrate) == (44100, "m4a", None)
    assert o.video is None
    assert o.mode == "audio"
    assert o.name_template == "%(title)s"
    assert o.output is None
    assert not o.output_is_file
    assert o.warnings == ()


def test_defaults_video() -> None:
    o = parse("-v", URL)
    assert o.video is not None
    assert (o.video.max_height, o.video.fmt, o.video.strict) == (1080, "mp4", False)
    assert parse("-v", "--resolution", "best", URL).video.max_height is None  # type: ignore[union-attr]
    assert parse("-v", "--resolution", "2160", "--video-format", "mkv", URL).video.fmt == "mkv"  # type: ignore[union-attr]


def test_opus_rules_S3() -> None:
    assert parse("-a", "--audio-format", "opus", URL).audio.sample_rate == 48000  # type: ignore[union-attr]
    assert parse("-a", "--audio-format", "opus", "--sample-rate", "48000", URL).audio
    assert "48000" in fails("-a", "--audio-format", "opus", "--sample-rate", "44100", URL)


def test_high_rates_warn_and_mp3_limit() -> None:
    o = parse("-a", "--sample-rate", "96000", URL)
    assert o.audio is not None
    assert o.audio.sample_rate == 96000
    assert "upsampled" in o.warnings[0]
    assert "mp3" in fails("-a", "--audio-format", "mp3", "--sample-rate", "96000", URL)
    assert parse("-a", "--audio-format", "wav", "--sample-rate", "96000", URL).audio


@pytest.mark.parametrize("bad", ["192", "k", "1920k", "abc", "5k", "192kb", ""])
def test_bad_bitrate(bad: str) -> None:
    assert "--audio-quality" in fails("-a", "--audio-quality", bad, URL)


def test_bitrate_ok_and_lossless_ignored() -> None:
    assert parse("-a", "--audio-quality", "192K", URL).audio.bitrate == "192k"  # type: ignore[union-attr]
    o = parse("-a", "--audio-format", "flac", "--audio-quality", "192k", URL)
    assert o.audio is not None
    assert o.audio.bitrate is None
    assert "ignored" in o.warnings[0]


@pytest.mark.parametrize(
    "flags",
    [
        ("--audio-format", "aac"),
        ("--audio-format", "MP4"),
    ],
)
def test_bad_audio_format(flags: tuple[str, ...]) -> None:
    assert "valid formats" in fails("-a", *flags, URL)


def test_bad_video_values() -> None:
    assert "valid values" in fails("-v", "--resolution", "999", URL)
    assert "valid formats" in fails("-v", "--video-format", "avi", URL)


def test_quiet_verbose() -> None:
    assert "cannot be used together" in fails("-a", "-q", "--verbose", URL)
    o = parse("-a", "-q", URL)
    assert o.quiet and not o.verbose


def test_output_dir_vs_file(tmp_path: Path) -> None:
    assert not parse("-a", "-o", str(tmp_path), URL).output_is_file
    assert not parse("-a", "-o", "out/", URL).output_is_file
    assert not parse("-a", "-o", "outdir", URL).output_is_file
    o = parse("-a", "-o", "x.m4a", URL)
    assert o.output_is_file
    assert o.output == "x.m4a"


def test_output_extension_must_match() -> None:
    assert "does not match" in fails("-a", "-o", "file.mp3", URL)
    assert "does not match" in fails("-v", "-o", "file.mkv", URL)
    assert parse("-v", "--video-format", "mkv", "-o", "f.MKV", URL).output_is_file
    assert parse("-a", "--audio-format", "mp3", "-o", "f.mp3", URL).output_is_file


def test_output_file_with_name_is_error() -> None:
    assert "--name" in fails("-a", "-o", "x.m4a", "-n", "foo", URL)
    assert parse("-a", "-o", "dir/", "-n", "foo", URL).name_template == "foo"


def test_bad_template_and_empty_output() -> None:
    assert "unknown field" in fails("-a", "-n", "%(nope)s", URL)
    assert "invalid" in fails("-a", "-n", "100%", URL)
    assert "empty" in fails("-a", "-o", " ", URL)


def test_list_formats_needs_no_mode() -> None:
    o = parse("--list-formats", URL)
    assert o.mode is None and o.list_formats
    assert o.audio is None and o.video is None
    assert "requires -a" in fails("--list-formats", "--sample-rate", "48000", URL)
    assert parse("--list-formats", "-a", URL).audio is not None


def test_no_playlist_is_noop_and_playlist_url_ok() -> None:
    o = parse("-a", "--no-playlist", f"{URL}?list=PLabc")
    assert o.url.video_id == "dQw4w9WgXcQ"
    assert "playlists are not supported" in fails("-a", "https://www.youtube.com/playlist?list=PL1")


def test_unknown_flag_and_abbrev() -> None:
    fails("-a", "--bogus", URL)
    fails("-a", "--sample", "48000", URL)  # abbreviations are disabled
