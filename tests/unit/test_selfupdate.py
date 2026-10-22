from __future__ import annotations

import hashlib
import io
import tarfile
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from xtractor import selfupdate
from xtractor.cli import main
from xtractor.errors import FileSystemError, InternalError, NetworkError, UsageError
from xtractor.selfupdate import (
    SelfUpdater,
    is_homebrew_path,
    is_newer,
    parse_sums,
    parse_version,
    resolve_repo,
)

REPO = "acme/Xtractor"
NEW = "1.2.0"
TAR = f"Xtractor-{NEW}-macos-arm64.tar.gz"
BASE = "https://example.invalid/dl/"


def make_tar(payload: bytes = b"NEW-BINARY") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (
            (f"Xtractor-{NEW}/LICENSE", b"mit"),
            (f"Xtractor-{NEW}/Xtractor", payload),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeFetcher:
    def __init__(
        self,
        tag: str = f"v{NEW}",
        tar: bytes | None = None,
        sums: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.tar = tar if tar is not None else make_tar()
        digest = hashlib.sha256(self.tar).hexdigest()
        self.sums = sums if sums is not None else f"{digest}  {TAR}\n"
        self.release = {
            "tag_name": tag,
            "assets": [
                {"name": TAR, "browser_download_url": BASE + TAR},
                {"name": "SHA256SUMS", "browser_download_url": BASE + "SHA256SUMS"},
            ],
        }
        self.error = error
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.release

    def download(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        if self.error:
            raise self.error
        dest.write_bytes(self.tar if url.endswith(".tar.gz") else self.sums.encode())


@pytest.fixture
def exe(tmp_path: Path) -> Path:
    p = tmp_path / "bin" / "Xtractor"
    p.parent.mkdir()
    p.write_bytes(b"OLD-BINARY")
    p.chmod(0o755)
    return p


def updater(fetcher: FakeFetcher, exe: Path, **kw: Any) -> SelfUpdater:
    defaults: dict[str, Any] = {
        "current_version": "1.0.0",
        "executable": exe,
        "frozen": True,
        "repo": REPO,
        "signer": lambda p: None,
        "verifier": lambda p, v: True,
        "log": lambda m: None,
    }
    defaults.update(kw)
    return SelfUpdater(fetcher=fetcher, **defaults)


@pytest.mark.parametrize(
    ("a", "b", "newer"),
    [
        ("1.0.1", "1.0.0", True),
        ("v1.10.0", "1.9.9", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.0", "1.0.1", False),
        ("1.0.0", "1.0.0-rc.2", True),
        ("1.0.0-rc.2", "1.0.0-rc.1", True),
        ("1.0.0-rc.1", "1.0.0", False),
        ("1.0.0rc1", "1.0.0-rc.1", False),
        ("1.0.0-beta.1", "1.0.0-alpha.9", True),
        ("2.0.0", "1.99.99", True),
    ],
)
def test_version_compare(a: str, b: str, newer: bool) -> None:
    assert is_newer(a, b) is newer


def test_bad_version() -> None:
    with pytest.raises(InternalError):
        parse_version("latest")


def test_parse_sums() -> None:
    h = "a" * 64
    assert parse_sums(f"{h}  x.tar.gz\n{h.upper()} *dist/y\njunk\n") == {"x.tar.gz": h, "y": h}


def test_update_replaces_binary_and_keeps_backup(exe: Path) -> None:
    f = FakeFetcher()
    assert updater(f, exe).run() == NEW
    assert exe.read_bytes() == b"NEW-BINARY"
    assert exe.with_name("Xtractor.bak").read_bytes() == b"OLD-BINARY"
    assert not [p for p in exe.parent.iterdir() if p.name.startswith(".")]  # staging cleaned
    assert f.urls[0] == f"https://api.github.com/repos/{REPO}/releases/latest"


def test_up_to_date_does_not_download(exe: Path) -> None:
    f = FakeFetcher(tag="v1.0.0")
    assert updater(f, exe).run() == "1.0.0"
    assert len(f.urls) == 1
    assert exe.read_bytes() == b"OLD-BINARY"


def test_checksum_mismatch_leaves_old_binary(exe: Path) -> None:
    f = FakeFetcher(sums=f"{'0' * 64}  {TAR}\n")
    with pytest.raises(InternalError, match="checksum mismatch"):
        updater(f, exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"
    assert not exe.with_name("Xtractor.bak").exists()


def test_missing_sums_entry(exe: Path) -> None:
    with pytest.raises(InternalError, match="no entry"):
        updater(FakeFetcher(sums=f"{'0' * 64}  other.tar.gz\n"), exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"


def test_corrupt_archive_with_valid_checksum(exe: Path) -> None:
    junk = b"not a tarball"
    with pytest.raises(InternalError, match="corrupt"):
        updater(FakeFetcher(tar=junk), exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"


def test_archive_without_binary(exe: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("LICENSE")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(InternalError, match="does not contain"):
        updater(FakeFetcher(tar=buf.getvalue()), exe).run()


def test_new_binary_failing_selfcheck_is_not_installed(exe: Path) -> None:
    with pytest.raises(InternalError, match="self-check"):
        updater(FakeFetcher(), exe, verifier=lambda p, v: False).run()
    assert exe.read_bytes() == b"OLD-BINARY"


def test_rollback_when_installed_binary_fails_verification(exe: Path) -> None:
    calls: list[Path] = []

    def verifier(path: Path, version: str) -> bool:
        calls.append(path)
        return path != exe  # staged copy passes, installed one fails

    with pytest.raises(InternalError, match="rolled back"):
        updater(FakeFetcher(), exe, verifier=verifier).run()
    assert exe.read_bytes() == b"OLD-BINARY"
    assert len(calls) == 2


def test_replace_failure_maps_to_filesystem_error(
    exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src: object, dst: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(selfupdate.os, "replace", boom)
    with pytest.raises(FileSystemError):
        updater(FakeFetcher(), exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"


def test_unwritable_directory_exit_7(exe: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfupdate.os, "access", lambda *a, **k: False)
    f = FakeFetcher()
    with pytest.raises(FileSystemError) as info:
        updater(f, exe).run()
    assert info.value.exit_code == 7
    assert len(f.urls) == 1  # nothing downloaded


def test_signer_is_called_on_staged_binary(exe: Path) -> None:
    signed: list[bytes] = []
    updater(FakeFetcher(), exe, signer=lambda p: signed.append(p.read_bytes())).run()
    assert signed == [b"NEW-BINARY"]


def test_not_frozen_prints_pipx_hint_without_network(exe: Path) -> None:
    f = FakeFetcher()
    with pytest.raises(UsageError, match="pipx upgrade Xtractor"):
        updater(f, exe, frozen=False).run()
    assert f.urls == []


def test_homebrew_path_refused(tmp_path: Path) -> None:
    cellar = tmp_path / "Cellar" / "xtractor" / "1.0.0" / "bin"
    cellar.mkdir(parents=True)
    brew_exe = cellar / "Xtractor"
    brew_exe.write_bytes(b"x")
    assert is_homebrew_path(brew_exe)
    with pytest.raises(UsageError, match="brew upgrade"):
        updater(FakeFetcher(), brew_exe).run()


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("nodename nor servname provided"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        urllib.error.HTTPError("u", 503, "unavailable", None, None),  # type: ignore[arg-type]
        urllib.error.HTTPError("u", 403, "rate limited", None, None),  # type: ignore[arg-type]
        urllib.error.HTTPError("u", 404, "nf", None, None),  # type: ignore[arg-type]
    ],
)
def test_offline_maps_to_network_error(exe: Path, error: BaseException) -> None:
    with pytest.raises(NetworkError) as info:
        updater(FakeFetcher(error=error), exe).run()
    assert info.value.exit_code == 4
    assert exe.read_bytes() == b"OLD-BINARY"


def test_release_missing_assets(exe: Path) -> None:
    f = FakeFetcher()
    f.release["assets"] = []
    with pytest.raises(InternalError, match="missing"):
        updater(f, exe).run()


def test_garbage_api_response(exe: Path) -> None:
    f = FakeFetcher()
    f.release = ["nope"]  # type: ignore[assignment]
    with pytest.raises(InternalError, match="unexpected response"):
        updater(f, exe).run()


def test_repo_default_is_the_real_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(selfupdate.REPO_ENV, raising=False)
    assert resolve_repo() == "BelongaGezza/Xtractor"


def test_repo_placeholder_fails_clearly() -> None:
    with pytest.raises(UsageError, match="not configured"):
        resolve_repo({selfupdate.REPO_ENV: "OWNER/Xtractor"})


def test_repo_env_override_and_validation() -> None:
    assert resolve_repo({selfupdate.REPO_ENV: "me/Xtractor"}) == "me/Xtractor"
    with pytest.raises(UsageError, match="invalid"):
        resolve_repo({selfupdate.REPO_ENV: "../evil"})


def test_cli_self_update_not_frozen(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--self-update"]) == 2
    err = capsys.readouterr()
    assert "pipx upgrade Xtractor" in err.err
    assert err.out == ""


def test_cli_self_update_rejects_other_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--self-update", "-a", "https://youtu.be/dQw4w9WgXcQ"]) == 2


def test_cli_self_update_success_prints_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("xtractor.cli.run_self_update", lambda: (print("9.9.9"), 0)[1])  # stdout-ok
    assert main(["--self-update"]) == 0


def test_help_and_version_never_touch_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    assert main(["--version"]) == 0
    assert main(["-h"]) == 0
