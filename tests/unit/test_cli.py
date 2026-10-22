from __future__ import annotations

import pytest

from xtractor import __version__
from xtractor.cli import LEGAL_NOTICE, build_parser, main
from xtractor.errors import EXIT_CODE_TABLE
from xtractor.options import (
    AUDIO_FORMATS,
    RESOLUTIONS,
    SAMPLE_RATES,
    VIDEO_FORMATS,
)

URL = "https://youtu.be/dQw4w9WgXcQ"


@pytest.fixture
def no_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")


def help_text(capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(["-h"])
    assert info.value.code == 0
    return " ".join(capsys.readouterr().out.split())


# AC1: help lists every option with defaults, works without ffmpeg.
def test_help_exit0_without_ffmpeg(no_path: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-h"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: Xtractor [OPTIONS] URL")


def test_help_lists_every_option_and_default(capsys: pytest.CaptureFixture[str]) -> None:
    text = help_text(capsys)
    for flag in (
        "-a, --audio",
        "-v, --video",
        "--sample-rate HZ",
        "--audio-format FMT",
        "--audio-quality BR",
        "--resolution RES",
        "--video-format FMT",
        "--strict-format",
        "-o, --output PATH",
        "-n, --name TEMPLATE",
        "--overwrite",
        "-q, --quiet",
        "--verbose",
        "--list-formats",
        "--no-playlist",
        "--version",
        "-h, --help",
    ):
        assert flag in text, flag
    for choice in (*map(str, SAMPLE_RATES), *AUDIO_FORMATS, *RESOLUTIONS, *VIDEO_FORMATS):
        assert choice in text
    for default in (
        "[default: 44100",
        "[default: m4a]",
        "[default: 1080]",
        "[default: mp4]",
        "[default: current dir]",
        '[default: "%(title)s"]',
        "128k",
    ):
        assert default in text, default
    assert "Mode (exactly one required):" in text
    assert "Audio options (with -a):" in text
    assert "Video options (with -v):" in text
    assert "General:" in text
    assert "Examples:" in text
    assert "Xtractor -a https://youtu.be/VIDEOID" in text


def test_help_has_exit_codes_and_legal_notice(capsys: pytest.CaptureFixture[str]) -> None:
    text = help_text(capsys)
    for code, _ in EXIT_CODE_TABLE:
        assert f" {code} " in text
    assert " ".join(LEGAL_NOTICE.split()) in text
    assert "130" in text


def test_no_drm_or_auth_options_exist() -> None:
    flags = {s for a in build_parser()._actions for s in a.option_strings}
    assert not {f for f in flags if any(w in f for w in ("drm", "cookie", "username", "password"))}


def test_version_without_ffmpeg(no_path: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"Xtractor {__version__}"


def test_usage_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([URL]) == 2
    err = capsys.readouterr()
    assert err.out == ""
    assert err.err.startswith("Xtractor: error:")
    assert main(["-a", "-v", URL]) == 2
    assert main(["-a", "--sample-rate", "12345", URL]) == 2
    assert "44100" in capsys.readouterr().err
    assert main(["-a", "--bogus"]) == 2
    assert main([]) == 2


def test_missing_ffmpeg_exits_5(no_path: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-a", URL]) == 5
    assert "ffmpeg" in capsys.readouterr().err


def test_list_formats_skips_ffmpeg_check(no_path: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-formats", URL]) == 1  # reaches the stub, not exit 5
    assert "not implemented" in capsys.readouterr().err


def test_valid_args_stop_at_not_implemented(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("xtractor.cli.ensure_dependencies", lambda: None)
    assert main(["-a", "--sample-rate", "96000", URL]) == 1
    cap = capsys.readouterr()
    assert cap.out == ""
    assert "warning" in cap.err and "not implemented yet" in cap.err
    assert main(["-a", "-q", "--sample-rate", "96000", URL]) == 1
    assert "warning" not in capsys.readouterr().err


def test_verbose_prints_traceback(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("xtractor.cli.ensure_dependencies", lambda: None)
    assert main(["-a", "--verbose", URL]) == 1
    assert "Traceback" in capsys.readouterr().err


def test_keyboard_interrupt_exits_130(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("xtractor.cli.ensure_dependencies", boom)
    assert main(["-a", URL]) == 130
    assert "interrupted" in capsys.readouterr().err
