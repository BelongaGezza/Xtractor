from __future__ import annotations

import errno
import io
import os
import signal
from pathlib import Path

import pytest

from tests.unit.fakes import FakeExtractor, FakeFfmpeg
from xtractor import __version__
from xtractor.cli import LEGAL_NOTICE, build_parser, main
from xtractor.errors import EXIT_CODE_TABLE, NetworkError, VideoUnavailable
from xtractor.options import (
    AUDIO_FORMATS,
    RESOLUTIONS,
    SAMPLE_RATES,
    VIDEO_FORMATS,
    Options,
)
from xtractor.pipeline import Deps
from xtractor.ui import Reporter

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
    assert "Mode (exactly one required, except for" in text
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


def test_list_formats_needs_js_runtime_but_not_ffmpeg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # neither ffmpeg nor a JS runtime
    assert main(["--list-formats", URL]) == 5
    err = capsys.readouterr().err
    assert "JavaScript runtime" in err and "ffmpeg" not in err and "deno" in err
    fake_js = tmp_path / "deno"
    fake_js.write_text("#!/bin/sh\n")
    fake_js.chmod(0o755)
    monkeypatch.setattr("xtractor.ytdlp.YtDlpExtractor", lambda **kw: FakeExtractor())
    assert main(["--list-formats", URL]) == 0
    assert capsys.readouterr().out.startswith("ID")


def test_missing_js_runtime_exits_5_for_downloads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ff = tmp_path / "ffmpeg"
    ff.write_text("#!/bin/sh\n")
    ff.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert main(["-a", URL]) == 5
    assert "JavaScript runtime" in capsys.readouterr().err


def test_help_and_version_never_check_dependencies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(**_: object) -> None:
        raise AssertionError("dependencies must not be resolved")

    monkeypatch.setattr("xtractor.tools.ensure_dependencies", boom)
    assert main(["-h"]) == 0
    assert main(["--version"]) == 0
    assert main(["-a", "--sample-rate", "1", URL]) == 2  # usage errors come first
    capsys.readouterr()


def patch_deps(
    monkeypatch: pytest.MonkeyPatch,
    ex: FakeExtractor | None = None,
    ff: FakeFfmpeg | None = None,
) -> FakeExtractor:
    ex = ex or FakeExtractor()
    ffm = ff or FakeFfmpeg()

    def build(opts: Options, reporter: Reporter) -> Deps:
        return Deps(ex, reporter, ffm, "ffmpeg")

    monkeypatch.setattr("xtractor.cli._build_deps", build)
    return ex


def test_stdout_is_exactly_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_deps(monkeypatch)
    assert main(["-a", "--sample-rate", "96000", "-o", str(tmp_path), URL]) == 0
    cap = capsys.readouterr()
    assert cap.out == f"{tmp_path / 'My Title.m4a'}\n"
    assert "warning" in cap.err and "upsampled" in cap.err
    assert main(["-a", "-q", "--overwrite", "-o", str(tmp_path), URL]) == 0
    cap = capsys.readouterr()
    assert cap.out == f"{tmp_path / 'My Title.m4a'}\n"
    assert cap.err == ""


def test_skip_existing_prints_path_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_deps(monkeypatch)
    assert main(["-a", "-o", str(tmp_path), URL]) == 0
    capsys.readouterr()
    assert main(["-a", "-o", str(tmp_path), URL]) == 0
    cap = capsys.readouterr()
    assert cap.out == f"{tmp_path / 'My Title.m4a'}\n"
    assert "exists, skipping" in cap.err


def test_list_formats_table_on_stdout(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_deps(monkeypatch)
    assert main(["--list-formats", "-q", URL]) == 0
    cap = capsys.readouterr()
    assert cap.out.startswith("ID") and "audio only" in cap.out
    assert cap.err == ""


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (VideoUnavailable("private"), 3),
        (NetworkError("down"), 4),
        (OSError(errno.ENOSPC, "No space left on device"), 7),
        (OSError(errno.EACCES, "Permission denied"), 7),
        (RuntimeError("boom"), 1),
    ],
)
def test_error_mapping_through_main(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
    code: int,
) -> None:
    patch_deps(monkeypatch, FakeExtractor(fail_probe=exc))
    assert main(["-a", "-o", str(tmp_path), URL]) == code
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err.rstrip().splitlines()[-1].startswith("Xtractor: error:")
    assert list(tmp_path.iterdir()) == []


def test_verbose_prints_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_deps(monkeypatch, FakeExtractor(fail_probe=RuntimeError("boom")))
    assert main(["-a", "--verbose", "-o", str(tmp_path), URL]) == 1
    assert "Traceback" in capsys.readouterr().err


def test_keyboard_interrupt_exits_130_and_cleans_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(_: Path) -> None:
        raise KeyboardInterrupt

    patch_deps(monkeypatch, FakeExtractor(on_download=interrupt))
    out = tmp_path / "out"
    assert main(["-a", "-o", str(out), URL]) == 130
    cap = capsys.readouterr()
    assert cap.out == "" and "interrupted" in cap.err
    assert not out.exists()


def test_sigterm_is_handled_like_ctrl_c(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def term(_: Path) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    patch_deps(monkeypatch, FakeExtractor(on_download=term))
    assert main(["-a", "-o", str(tmp_path / "o"), URL]) == 130
    assert not (tmp_path / "o").exists()
    capsys.readouterr()
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL


def test_build_deps_wires_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from xtractor import cli
    from xtractor.tools import JsRuntime, ToolPaths

    ff = tmp_path / "ffmpeg"
    js = JsRuntime("deno", tmp_path / "deno")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "xtractor.tools.ensure_dependencies", lambda **kw: seen.update(kw) or ToolPaths(ff, js)
    )
    opts = cli.parse_args(["-a", URL])
    deps = cli._build_deps(opts, Reporter(stream=io.StringIO()))
    assert seen == {"need_ffmpeg": True, "need_js": True}
    assert deps.ffmpeg_bin == ff
    fl = cli.parse_args(["--list-formats", URL])
    monkeypatch.setattr("xtractor.tools.ensure_dependencies", lambda **kw: ToolPaths(None, js))
    assert cli._build_deps(fl, Reporter(stream=io.StringIO())).ffmpeg_bin == "ffmpeg"


README = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_documents_every_option_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    readme = README.read_text()
    flags = {s for a in build_parser()._actions for s in a.option_strings if s.startswith("-")}
    assert "--self-update" in flags
    missing = [f for f in sorted(flags) if f"`{f}`" not in readme and f"`{f} " not in readme]
    assert missing == []


def test_readme_legal_notice_identical_to_help() -> None:
    text = " ".join(line.removeprefix("> ") for line in README.read_text().splitlines())
    assert " ".join(LEGAL_NOTICE.split()) in " ".join(text.split())


def test_readme_documents_defaults_and_exit_codes() -> None:
    readme = README.read_text()
    for code, _ in EXIT_CODE_TABLE:
        assert f"| {code} |" in readme
    for rate in SAMPLE_RATES:
        assert str(rate) in readme
    for fmt in (*AUDIO_FORMATS, *VIDEO_FORMATS, *RESOLUTIONS):
        assert fmt in readme
    assert "xattr -d com.apple.quarantine" in readme


def test_help_and_version_do_not_import_heavy_modules() -> None:
    """Onefile start-up budget: -h/--version must not load these (see docs/BUILD_NOTES.md)."""
    import subprocess
    import sys

    code = (
        "import sys; from xtractor.cli import main\n"
        "for a in (['--version'], ['-h']):\n"
        "    main(a)\n"
        "bad = [m for m in ('yt_dlp', 'xtractor.ytdlp', 'xtractor.pipeline', 'xtractor.selfupdate',"
        " 'xtractor.tools', 'xtractor.bundle', 'xtractor.ffmpeg', 'subprocess', 'hashlib', 'ssl',"
        " 'shutil', 'tempfile') if m in sys.modules]\n"
        "sys.stderr.write(repr(bad))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert r.stderr.strip().endswith("[]"), r.stderr
