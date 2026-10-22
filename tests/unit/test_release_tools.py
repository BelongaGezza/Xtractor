"""scripts/release_tools.py: manifest + blob module feed bundle.py; tarball is reproducible."""

from __future__ import annotations

import importlib.util
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

from xtractor import bundle

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_tools.py"


def load_tools() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_tools", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_blob_round_trips_through_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"\x00ffmpeg\xff" * 100)
    qjs = tmp_path / "qjs"
    qjs.write_bytes(b"qjs-bytes")
    tools = load_tools()
    stage = tmp_path / "stage"
    tools.write_manifest(stage, "1.2.3", ffmpeg, qjs, "quickjs")

    monkeypatch.syspath_prepend(str(stage / "blob"))
    monkeypatch.delitem(sys.modules, "xtractor_blob", raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.delenv("XTRACTOR_BUNDLE_DIR", raising=False)
    monkeypatch.setenv("XTRACTOR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(bundle, "_adhoc_sign_if_needed", lambda p: None)

    found = bundle.bundled_js()
    assert found is not None
    name, path = found
    assert name == "quickjs"
    assert path.read_bytes() == b"qjs-bytes"
    assert path.parent.name.startswith("1.2.3-")
    ff = bundle.bundled_asset_path("ffmpeg")
    assert ff is not None
    assert ff.read_bytes() == ffmpeg.read_bytes()
    monkeypatch.delitem(sys.modules, "xtractor_blob", raising=False)


def test_tarball_is_flat_and_reproducible(tmp_path: Path) -> None:
    tools = load_tools()
    binary = tmp_path / "Xtractor"
    binary.write_bytes(b"binary")
    lic = tmp_path / "LICENSE"
    lic.write_text("mit")
    notices = tmp_path / "NOTICES"
    notices.write_text("notices")
    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    tools.make_tarball(a, binary, lic, notices)
    tools.make_tarball(b, binary, lic, notices)
    assert a.read_bytes() == b.read_bytes()
    with tarfile.open(a) as tf:
        assert [m.name for m in tf] == ["Xtractor", "LICENSE", "THIRD_PARTY_NOTICES"]
        member = tf.getmember("Xtractor")
        assert member.mode == 0o755
        extracted = tf.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b"binary"
