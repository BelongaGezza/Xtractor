from __future__ import annotations

from pathlib import Path

import pytest

from xtractor import tools
from xtractor.errors import MissingDependency

REAL_RUNTIME_VERSION = tools._runtime_version  # captured before the autouse stub


def make_exe(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


@pytest.fixture(autouse=True)
def no_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_bundled_js_runtime", lambda: None)
    monkeypatch.setattr(tools, "_runtime_version", lambda path: (99, 0))


def test_preference_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    make_exe(tmp_path, "bun")
    assert tools.locate_js_runtime().name == "bun"
    q = make_exe(tmp_path, "qjs")
    rt = tools.locate_js_runtime()
    assert (rt.name, rt.path) == ("quickjs", q)  # yt-dlp key is "quickjs", binary is qjs
    make_exe(tmp_path, "node")
    assert tools.locate_js_runtime().name == "node"
    d = make_exe(tmp_path, "deno")
    rt = tools.locate_js_runtime()
    assert (rt.name, rt.path) == ("deno", d)


def test_bundled_fallback_and_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(MissingDependency) as info:
        tools.locate_js_runtime()
    assert info.value.exit_code == 5 and "deno" in str(info.value)
    bundled = make_exe(tmp_path, "deno")
    monkeypatch.setattr(tools, "_bundled_js_runtime", lambda: tools.JsRuntime("deno", bundled))
    assert tools.locate_js_runtime().path == bundled
    monkeypatch.setattr(
        tools, "_bundled_js_runtime", lambda: tools.JsRuntime("deno", tmp_path / "gone")
    )
    with pytest.raises(MissingDependency):
        tools.locate_js_runtime()


def test_path_wins_over_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    on_path = make_exe(tmp_path, "deno")
    monkeypatch.setenv("PATH", str(tmp_path))
    other = tmp_path / "elsewhere"
    monkeypatch.setattr(tools, "_bundled_js_runtime", lambda: tools.JsRuntime("deno", other))
    assert tools.locate_js_runtime().path == on_path


def test_ensure_dependencies_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    assert tools.ensure_dependencies(need_ffmpeg=False, need_js=False) == tools.ToolPaths(
        None, None
    )
    with pytest.raises(MissingDependency, match="ffmpeg"):
        tools.ensure_dependencies(need_ffmpeg=True, need_js=False)
    with pytest.raises(MissingDependency, match="JavaScript"):
        tools.ensure_dependencies(need_ffmpeg=False, need_js=True)
    ff = make_exe(tmp_path, "ffmpeg")
    js = make_exe(tmp_path, "deno")
    monkeypatch.setenv("PATH", str(tmp_path))
    got = tools.ensure_dependencies(need_ffmpeg=True, need_js=True)
    assert got.ffmpeg == ff and got.js_runtime is not None and got.js_runtime.path == js


def test_install_hint_per_platform() -> None:
    assert "brew install deno" in tools.js_runtime_install_hint("darwin")
    assert "deno.com" in tools.js_runtime_install_hint("linux")


def test_parse_runtime_version() -> None:
    assert tools.parse_runtime_version("deno 2.3.1 (stable, release, aarch64)\nv8 13.0") == (2, 3)
    assert tools.parse_runtime_version("v22.4.0\n") == (22, 4)
    assert tools.parse_runtime_version("garbage") is None


@pytest.mark.parametrize(
    ("name", "output", "ok"),
    [
        ("deno", "deno 2.2.9", False),
        ("deno", "deno 2.3.0", True),
        ("node", "v18.19.0", False),
        ("node", "v22.0.0", True),
        ("node", "", False),
    ],
)
def test_path_runtime_version_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, output: str, ok: bool
) -> None:
    exe = tmp_path / name
    exe.write_text(f"#!/bin/sh\necho '{output}'\n")
    exe.chmod(0o755)
    monkeypatch.setattr(tools, "_runtime_version", REAL_RUNTIME_VERSION)
    monkeypatch.setenv("PATH", str(tmp_path))
    if ok:
        assert tools.locate_js_runtime().name == name
    else:
        with pytest.raises(MissingDependency) as info:
            tools.locate_js_runtime()
        assert info.value.exit_code == 5 and "too old" in str(info.value)


def test_too_old_path_runtime_skipped_for_newer_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    make_exe(tmp_path, "deno")
    make_exe(tmp_path, "node")
    versions = {"deno": (2, 0), "node": (22, 1)}
    monkeypatch.setattr(tools, "_runtime_version", lambda p: versions[Path(p).name])
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tools.locate_js_runtime().name == "node"


def test_system_flag_with_too_old_runtime_falls_back_to_bundled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    make_exe(tmp_path, "deno")
    monkeypatch.setattr(tools, "_runtime_version", lambda p: (1, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("XTRACTOR_USE_SYSTEM_TOOLS", "1")
    bundled = make_exe(tmp_path, "bundled-deno")
    monkeypatch.setattr(tools, "_bundled_js_runtime", lambda: tools.JsRuntime("deno", bundled))
    assert tools.locate_js_runtime().path == bundled
    monkeypatch.setattr(tools, "_bundled_js_runtime", lambda: None)
    with pytest.raises(MissingDependency, match="too old"):
        tools.locate_js_runtime()


def test_real_version_probe_handles_missing_binary(tmp_path: Path) -> None:
    # the unwrapped probe: a nonexistent executable gives None, not a crash
    assert REAL_RUNTIME_VERSION(str(tmp_path / "nope")) is None
