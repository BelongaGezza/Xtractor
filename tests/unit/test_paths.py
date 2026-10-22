from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

from xtractor import paths
from xtractor.errors import UsageError

FIELDS = {"title": "My Song", "id": "dQw4w9WgXcQ", "uploader": "Chan", "upload_date": "20240131"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ("a/b:c?", "a b c"),
        ('he said "hi" <now> | * \\ ', "he said hi now"),
        ("tab\tand\nnewline\x00nul", "tab and newline nul"),
        ("trailing dots...", "trailing dots"),
        ("  spaced   out  ", "spaced out"),
        ("...", "video"),
        ("", "video"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("COM1", "_COM1"),
        ("console", "console"),
        ("Café – 日本語 🎵", "Café – 日本語 🎵"),
        ("café", "café"),
        ("; rm -rf ~ #", "; rm -rf ~ #"),
    ],
)
def test_sanitise(raw: str, expected: str) -> None:
    assert paths.sanitise(raw) == expected


def test_sanitise_fallback() -> None:
    assert paths.sanitise("???", fallback="abc") == "abc"


@pytest.mark.parametrize("ch", ["日", "🎵", "a"])
def test_sanitise_byte_cap_keeps_extension_room(ch: str) -> None:
    out = paths.sanitise(ch * 500, ext="m4a")
    assert len((out + ".m4a").encode()) <= paths.MAX_NAME_BYTES
    out.encode("utf-8")  # still valid UTF-8


def test_template() -> None:
    assert paths.expand_template("%(title)s [%(id)s]", FIELDS) == "My Song [dQw4w9WgXcQ]"
    assert paths.expand_template("100%%", FIELDS) == "100%"
    assert paths.expand_template("%(resolution)s", FIELDS) == "NA"
    with pytest.raises(UsageError, match="unknown field"):
        paths.validate_template("%(ext)s")
    for bad in ("", "50%", "%(title)"):
        with pytest.raises(UsageError):
            paths.validate_template(bad)


def test_resolve_dir_default_and_explicit(tmp_path: Path) -> None:
    kw = {"template": "%(title)s", "fields": FIELDS, "ext": "m4a", "output_is_file": False}
    assert paths.resolve_output(None, cwd=tmp_path, **kw) == tmp_path / "My Song.m4a"  # type: ignore[arg-type]
    assert paths.resolve_output("sub", cwd=tmp_path, **kw) == tmp_path / "sub" / "My Song.m4a"  # type: ignore[arg-type]
    abs_dir = tmp_path / "abs"
    assert paths.resolve_output(str(abs_dir), **kw) == abs_dir / "My Song.m4a"  # type: ignore[arg-type]


def test_resolve_hostile_title(tmp_path: Path) -> None:
    fields = {**FIELDS, "title": "a/b:c?../../etc"}
    out = paths.resolve_output(
        None, output_is_file=False, template="%(title)s", fields=fields, ext="mp3", cwd=tmp_path
    )
    assert out.parent == tmp_path
    assert "/" not in out.name and out.name.endswith(".mp3")


def test_resolve_empty_title_uses_id(tmp_path: Path) -> None:
    out = paths.resolve_output(
        None,
        output_is_file=False,
        template="%(title)s",
        fields={"title": "???", "id": "abc"},
        ext="wav",
        cwd=tmp_path,
    )
    assert out.name == "abc.wav"


def test_resolve_file(tmp_path: Path) -> None:
    kw = {"template": "x", "fields": FIELDS, "output_is_file": True}
    assert paths.resolve_output("o.m4a", ext="m4a", cwd=tmp_path, **kw) == tmp_path / "o.m4a"  # type: ignore[arg-type]
    with pytest.raises(UsageError, match="extension"):
        paths.resolve_output("o.mp3", ext="m4a", cwd=tmp_path, **kw)  # type: ignore[arg-type]


def test_looks_like_file(tmp_path: Path) -> None:
    assert not paths.looks_like_file(str(tmp_path))
    assert not paths.looks_like_file("a/")
    assert not paths.looks_like_file("noext")
    assert paths.looks_like_file("a.mp3")
    (tmp_path / "dir.d").mkdir()
    assert not paths.looks_like_file(str(tmp_path / "dir.d"))


def test_should_skip(tmp_path: Path) -> None:
    f = tmp_path / "f.m4a"
    assert not paths.should_skip(f, overwrite=False)
    f.write_text("x")
    assert paths.should_skip(f, overwrite=False)
    assert not paths.should_skip(f, overwrite=True)


def test_temp_workdir_cleans_on_success_and_failure(tmp_path: Path) -> None:
    with paths.temp_workdir(tmp_path / "new") as tmp:
        assert tmp.parent == tmp_path / "new"
        assert tmp.name.startswith(".Xtractor-")
        (tmp / "partial.part").write_text("x")
    assert list((tmp_path / "new").iterdir()) == []

    (tmp_path / "keep.txt").write_text("keep")
    with pytest.raises(RuntimeError), paths.temp_workdir(tmp_path) as tmp:
        (tmp / "partial").write_text("x")
        raise RuntimeError("mid-run failure")
    assert [p.name for p in tmp_path.iterdir() if p.name != "new"] == ["keep.txt"]


def test_failure_preserves_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "song.m4a"
    target.write_text("original")
    with pytest.raises(RuntimeError), paths.temp_workdir(tmp_path) as tmp:
        (tmp / "song.tmp.m4a").write_text("new")
        raise RuntimeError
    assert target.read_text() == "original"


def test_atomic_move_replaces(tmp_path: Path) -> None:
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_text("new")
    dst.write_text("old")
    paths.atomic_move(src, dst)
    assert dst.read_text() == "new"
    assert not src.exists()


def test_sigterm_becomes_keyboard_interrupt(tmp_path: Path) -> None:
    before = signal.getsignal(signal.SIGTERM)
    with (
        pytest.raises(KeyboardInterrupt),
        paths.sigterm_as_interrupt(),
        paths.temp_workdir(tmp_path),
    ):
        os.kill(os.getpid(), signal.SIGTERM)
        signal.pause()
    assert signal.getsignal(signal.SIGTERM) is before
    assert list(tmp_path.iterdir()) == []
