from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from xtractor import _selftest

ENTRY = Path(__file__).resolve().parents[2] / "packaging" / "entry.py"


def fake_bundle(tmp: Path, ffmpeg_body: str, js_body: str) -> Path:
    d = tmp / "b"
    d.mkdir()
    assets = {}
    for key, name, body in (("ffmpeg", "ffmpeg", ffmpeg_body), ("qjs", "qjs", js_body)):
        data = body.encode()
        (d / name).write_bytes(data)
        assets[key] = {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    manifest = {"app_version": "0", "assets": assets, "js": {"name": "quickjs", "asset": "qjs"}}
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XTRACTOR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("xtractor.bundle._adhoc_sign_if_needed", lambda p: None)
    return tmp_path


def test_selftest_passes_with_working_tools(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    b = fake_bundle(env, "#!/bin/sh\nexit 0\n", "#!/bin/sh\necho 42\n")
    monkeypatch.setenv("XTRACTOR_BUNDLE_DIR", str(b))
    assert _selftest.run() == 0
    assert "FAIL" not in capsys.readouterr().out


def test_selftest_fails_on_gpl_ffmpeg_and_bad_js(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    b = fake_bundle(env, "#!/bin/sh\necho '--enable-gpl'\nexit 1\n", "#!/bin/sh\necho 41\n")
    monkeypatch.setenv("XTRACTOR_BUNDLE_DIR", str(b))
    assert _selftest.run() == 1
    out = capsys.readouterr().out
    assert "FAIL ffmpeg is LGPL" in out
    assert "FAIL quickjs runs JavaScript" in out


def test_selftest_without_bundle_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR", raising=False)
    assert _selftest.run() == 1
    assert "FAIL embedded ffmpeg" in capsys.readouterr().out


def test_entry_selftest_flag_is_inert_without_env() -> None:
    import os

    env = {k: v for k, v in os.environ.items() if k != "XTRACTOR_SELFTEST"}
    r = subprocess.run(
        [sys.executable, str(ENTRY), "--xtractor-selftest"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert "selftest" not in r.stdout
    assert r.returncode == 2  # unknown option for the normal CLI
