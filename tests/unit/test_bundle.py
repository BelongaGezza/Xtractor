"""Embedded-tool extraction and the bundled-first resolution order (fake bundle, tmp cache)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from xtractor import bundle, ffmpeg, tools
from xtractor.errors import MissingDependency


def make_bundle(root: Path, *, js: bool = True) -> Path:
    d = root / "xtractor_bundle"
    d.mkdir()
    assets: dict[str, Any] = {}
    for key, name, body in (
        ("ffmpeg", "ffmpeg", b"#!/bin/sh\necho ff\n"),
        ("qjs", "qjs", b"#!/bin/sh\n"),
    ):
        (d / name).write_bytes(body)
        assets[key] = {"name": name, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    manifest: dict[str, Any] = {"app_version": "9.9.9", "assets": assets}
    if js:
        manifest["js"] = {"name": "quickjs", "asset": "qjs"}
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A fake bundle plus an isolated cache; returns the cache root."""
    bundle_path = make_bundle(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setenv("XTRACTOR_BUNDLE_DIR", str(bundle_path))
    monkeypatch.setenv("XTRACTOR_CACHE_DIR", str(cache))
    monkeypatch.delenv("XTRACTOR_USE_SYSTEM_TOOLS", raising=False)
    monkeypatch.setattr(bundle, "_adhoc_sign_if_needed", lambda p: None)
    return cache


def test_no_bundle_outside_frozen_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR", raising=False)
    assert bundle.bundle_source() is None
    assert bundle.bundled_asset_path("ffmpeg") is None
    assert bundle.bundled_js() is None
    assert ffmpeg._bundled_ffmpeg() is None
    assert tools._bundled_js_runtime() is None


def test_frozen_build_reads_the_blob_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: Path
) -> None:
    d = tmp_path / "xtractor_bundle"
    blob = types.ModuleType("xtractor_blob")
    blob.MANIFEST = (d / "manifest.json").read_text()  # type: ignore[attr-defined]
    blob.FILES = {n: (d / n).read_bytes() for n in ("ffmpeg", "qjs")}  # type: ignore[attr-defined]
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setenv("XTRACTOR_ALLOW_OVERRIDES", "1")  # the cache override is test-only
    monkeypatch.setitem(sys.modules, "xtractor_blob", blob)
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    assert path.read_bytes().endswith(b"echo ff\n")
    assert path.parent.parent == env


def test_frozen_without_blob_reports_nothing_bundled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.delitem(sys.modules, "xtractor_blob", raising=False)
    assert bundle.bundle_source() is None


def test_first_run_extracts_with_exec_bit_and_versioned_dir(env: Path) -> None:
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    assert path.parent.parent == env
    assert path.parent.name.startswith("9.9.9-")
    assert len(path.parent.name) == len("9.9.9-") + 8
    assert os.access(path, os.X_OK)
    assert path.read_bytes().endswith(b"echo ff\n")
    assert (path.parent.stat().st_mode & 0o777) == 0o700


def test_second_run_reuses_without_rewriting(env: Path) -> None:
    first = bundle.bundled_asset_path("ffmpeg")
    assert first is not None
    inode = first.stat().st_ino
    again = bundle.bundled_asset_path("ffmpeg")
    assert again == first
    assert again.stat().st_ino == inode


def test_corrupted_cache_file_is_re_extracted(env: Path) -> None:
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    path.write_bytes(b"garbage")
    fixed = bundle.bundled_asset_path("ffmpeg")
    assert fixed == path
    assert fixed.read_bytes().endswith(b"echo ff\n")


def test_missing_exec_bit_is_repaired(env: Path) -> None:
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    path.chmod(0o600)
    bundle.bundled_asset_path("ffmpeg")
    assert os.access(path, os.X_OK)


def test_unextractable_cache_raises_exit_5(env: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    os.environ["XTRACTOR_CACHE_DIR"] = str(blocker / "sub")
    with pytest.raises(MissingDependency) as info:
        bundle.bundled_asset_path("ffmpeg")
    assert info.value.exit_code == 5
    assert "XTRACTOR_USE_SYSTEM_TOOLS" in (info.value.hint or "")


def test_tampered_bundle_asset_is_refused(env: Path, tmp_path: Path) -> None:
    (tmp_path / "xtractor_bundle" / "ffmpeg").write_bytes(b"#!/bin/sh\nevil!!!!!!\n")
    with pytest.raises(MissingDependency):
        bundle.bundled_asset_path("ffmpeg")
    assert not list(env.glob("*/ffmpeg"))


def test_bad_manifest_raises(env: Path, tmp_path: Path) -> None:
    (tmp_path / "xtractor_bundle" / "manifest.json").write_text("{not json")
    with pytest.raises(MissingDependency):
        bundle.bundled_asset_path("ffmpeg")


def test_concurrent_first_runs_do_not_corrupt(env: Path) -> None:
    results: list[Path | Exception] = []

    def work() -> None:
        try:
            p = bundle.bundled_asset_path("ffmpeg")
            assert p is not None
            results.append(p)
        except Exception as exc:
            results.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(isinstance(r, Path) for r in results), results
    assert not list(env.glob("*/.*.tmp"))


def test_cache_key_changes_with_content(tmp_path: Path) -> None:
    first = tmp_path / "x"
    first.mkdir()
    a = bundle.load_manifest(bundle.DirSource(make_bundle(first)))
    other = tmp_path / "y"
    other.mkdir()
    d = make_bundle(other)
    m = json.loads((d / "manifest.json").read_text())
    m["assets"]["ffmpeg"]["sha256"] = "0" * 64
    (d / "manifest.json").write_text(json.dumps(m))
    b = bundle.load_manifest(bundle.DirSource(d))
    assert a.cache_key != b.cache_key
    assert a.cache_key.startswith("9.9.9-")


# ------------------------------------------------------------ resolution order
def _fake_path_tool(directory: Path, name: str) -> Path:
    directory.mkdir(exist_ok=True)
    p = directory / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


def test_ffmpeg_prefers_bundled_over_path(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_path_tool(tmp_path / "bin", "ffmpeg")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert ffmpeg.locate_ffmpeg().parent.parent == env


def test_ffmpeg_system_opt_in_prefers_path(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sys_ff = _fake_path_tool(tmp_path / "bin", "ffmpeg")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("XTRACTOR_USE_SYSTEM_TOOLS", "1")
    assert ffmpeg.locate_ffmpeg() == sys_ff
    monkeypatch.setenv("PATH", "/nonexistent")  # opt-in but nothing on PATH: fall back to bundled
    assert ffmpeg.locate_ffmpeg().parent.parent == env


def test_ffmpeg_falls_back_to_path_without_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR", raising=False)
    sys_ff = _fake_path_tool(tmp_path / "bin", "ffmpeg")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert ffmpeg.locate_ffmpeg() == sys_ff


def test_js_runtime_bundled_first_then_system(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    deno = _fake_path_tool(tmp_path / "bin", "deno")
    monkeypatch.setattr(tools, "_runtime_version", lambda path: (2, 5))  # PATH runtimes are gated
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    rt = tools.locate_js_runtime()
    assert rt.name == "quickjs"
    assert rt.path.name == "qjs"
    assert rt.path.parent.parent == env
    monkeypatch.setenv("XTRACTOR_USE_SYSTEM_TOOLS", "1")
    assert tools.locate_js_runtime().path == deno


def test_bundle_without_js_entry(env: Path, tmp_path: Path) -> None:
    m = json.loads((tmp_path / "xtractor_bundle" / "manifest.json").read_text())
    del m["js"]
    (tmp_path / "xtractor_bundle" / "manifest.json").write_text(json.dumps(m))
    assert bundle.bundled_js() is None


def test_adhoc_sign_runs_only_when_verify_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1 if argv[1] == "--verify" else 0)

    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(bundle.shutil, "which", lambda n: "/usr/bin/codesign")
    monkeypatch.setattr(bundle.subprocess, "run", fake_run)
    bundle._adhoc_sign_if_needed(tmp_path / "x")
    assert [c[1] for c in calls] == ["--verify", "--force"]
    calls.clear()

    def ok_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(bundle.subprocess, "run", ok_run)
    bundle._adhoc_sign_if_needed(tmp_path / "x")
    assert [c[1] for c in calls] == ["--verify"]


def test_overrides_are_inert_in_frozen_builds(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTRACTOR_ALLOW_OVERRIDES", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.delitem(sys.modules, "xtractor_blob", raising=False)
    assert not bundle.overrides_allowed()
    assert bundle.bundle_source() is None  # XTRACTOR_BUNDLE_DIR ignored
    assert bundle.cache_root() != env  # XTRACTOR_CACHE_DIR ignored
    monkeypatch.setenv("XTRACTOR_ALLOW_OVERRIDES", "1")
    assert bundle.bundle_source() is not None
    assert bundle.cache_root() == env


def test_cache_dirs_are_private(env: Path) -> None:
    env.mkdir(mode=0o777)
    env.chmod(0o777)
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    assert env.stat().st_mode & 0o777 == 0o700
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_symlinked_cache_root_is_refused(env: Path, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    env.symlink_to(real)
    with pytest.raises(MissingDependency):
        bundle.bundled_asset_path("ffmpeg")
    assert not list(real.iterdir())


def test_foreign_owner_is_refused(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env.mkdir(mode=0o700)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(env).st_uid + 1)
    with pytest.raises(MissingDependency):
        bundle.bundled_asset_path("ffmpeg")


def test_planted_symlink_at_tmp_name_is_not_followed(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = tmp_path / "victim"
    victim.write_text("KEEP")
    monkeypatch.setattr(bundle.secrets, "token_hex", lambda n: "0" * 16)
    cache = env / bundle.load_manifest(bundle.bundle_source()).cache_key  # type: ignore[arg-type]
    cache.mkdir(parents=True, mode=0o700)
    (cache / f".ffmpeg.{os.getpid()}.{'0' * 16}.tmp").symlink_to(victim)
    with pytest.raises(MissingDependency):
        bundle.bundled_asset_path("ffmpeg")
    assert victim.read_text() == "KEEP"


def test_symlinked_executable_is_not_valid(env: Path, tmp_path: Path) -> None:
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    real = tmp_path / "real-ffmpeg"
    real.write_bytes(path.read_bytes())
    real.chmod(0o755)
    path.unlink()
    path.symlink_to(real)
    fixed = bundle.bundled_asset_path("ffmpeg")
    assert fixed is not None
    assert not fixed.is_symlink()


def test_stale_cache_dirs_are_pruned(env: Path) -> None:
    env.mkdir(mode=0o700)
    old = env / "0.0.1-deadbeef"
    old.mkdir()
    (old / "ffmpeg").write_text("x")
    recent = env / "0.0.2-cafebabe"
    recent.mkdir()
    ancient = time_ago = os.stat(old).st_mtime - 7200
    os.utime(old, (ancient, time_ago))
    path = bundle.bundled_asset_path("ffmpeg")
    assert path is not None
    assert not old.exists()  # stale and older than the grace period
    assert recent.exists()  # too young: another version may be running
    assert path.exists()


def test_codesign_is_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class R:
        returncode = 1

    monkeypatch.setattr(bundle.sys, "platform", "darwin")
    monkeypatch.setattr(bundle.os, "access", lambda *a, **k: True)
    monkeypatch.setattr(bundle.subprocess, "run", lambda argv, **k: (calls.append(argv), R())[1])
    bundle._adhoc_sign_if_needed(tmp_path / "x")
    assert [c[0] for c in calls] == ["/usr/bin/codesign"] * 2
