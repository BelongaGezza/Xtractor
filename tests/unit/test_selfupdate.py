from __future__ import annotations

import base64
import hashlib
import io
import tarfile
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from xtractor import _ed25519, selfupdate
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
BASE = "https://github.com/acme/Xtractor/releases/download/v1.2.0/"
SEED = bytes(range(1, 33))


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
        sig: bytes | None = None,
        sign_sums: bool = True,
    ) -> None:
        self.tar = tar if tar is not None else make_tar()
        digest = hashlib.sha256(self.tar).hexdigest()
        self.sums = sums if sums is not None else f"{digest}  {TAR}\n"
        sums_b = self.sums.encode()
        if sig is not None:
            self.sig = sig
        else:
            raw = _ed25519.sign(SEED, selfupdate.SIGNED_PREFIX + sums_b)
            self.sig = base64.b64encode(raw)
        self.release = {
            "tag_name": tag,
            "assets": [
                {"name": TAR, "browser_download_url": BASE + TAR},
                {"name": "SHA256SUMS", "browser_download_url": BASE + "SHA256SUMS"},
                *(
                    [{"name": "SHA256SUMS.sig", "browser_download_url": BASE + "SHA256SUMS.sig"}]
                    if sign_sums
                    else []
                ),
            ],
        }
        self.error = error
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.release

    def download(self, url: str, dest: Path, max_bytes: int) -> None:
        self.urls.append(url)
        if self.error:
            raise self.error
        if url.endswith(".tar.gz"):
            data = self.tar
        elif url.endswith(".sig"):
            data = self.sig
        else:
            data = self.sums.encode()
        dest.write_bytes(data)


@pytest.fixture(autouse=True)
def trusted_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfupdate, "TRUSTED_PUBLIC_KEYS", (_ed25519.public_key(SEED).hex(),))


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
    assert exe.stat().st_mode & 0o777 == 0o755
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


def test_unsigned_release_is_refused(exe: Path) -> None:
    f = FakeFetcher(sign_sums=False)
    with pytest.raises(InternalError, match="not signed"):
        updater(f, exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"
    assert not any(u.endswith(".tar.gz") for u in f.urls)


@pytest.mark.parametrize("sig", [b"", b"!!notbase64!!", base64.b64encode(b"x" * 64), b"QUJD"])
def test_invalid_signature_is_refused(exe: Path, sig: bytes) -> None:
    f = FakeFetcher(sig=sig)
    with pytest.raises(InternalError, match="signature is invalid"):
        updater(f, exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"
    assert not any(u.endswith(".tar.gz") for u in f.urls)  # nothing big downloaded


def test_signature_by_untrusted_key_is_refused(exe: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = FakeFetcher()
    monkeypatch.setattr(selfupdate, "TRUSTED_PUBLIC_KEYS", (_ed25519.public_key(bytes(32)).hex(),))
    with pytest.raises(InternalError, match="signature is invalid"):
        updater(f, exe).run()


def test_key_rotation_accepts_any_listed_key(exe: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = _ed25519.public_key(bytes(32)).hex()
    monkeypatch.setattr(selfupdate, "TRUSTED_PUBLIC_KEYS", (old, _ed25519.public_key(SEED).hex()))
    assert updater(FakeFetcher(), exe).run() == NEW


def test_tampered_sums_after_signing_is_refused(exe: Path) -> None:
    f = FakeFetcher()
    f.sums = f.sums.replace("a", "b", 1) if "a" in f.sums else f.sums + "x"
    with pytest.raises(InternalError, match="signature is invalid"):
        updater(f, exe).run()


def test_rollback_replay_of_old_signed_release_is_refused(exe: Path) -> None:
    # A validly signed v1.1.0 payload published under a newer tag v1.2.0.
    old_tar = "Xtractor-1.1.0-macos-arm64.tar.gz"
    f = FakeFetcher(sums=f"{hashlib.sha256(make_tar()).hexdigest()}  {old_tar}\n")
    with pytest.raises(InternalError, match="no entry"):
        updater(f, exe).run()
    assert exe.read_bytes() == b"OLD-BINARY"


def test_downgrade_is_refused(exe: Path) -> None:
    f = FakeFetcher(tag="v0.9.0")
    assert updater(f, exe).run() == "1.0.0"
    assert len(f.urls) == 1


def test_odd_tag_is_refused(exe: Path) -> None:
    f = FakeFetcher(tag="v1.2.0-rc.1+build")
    with pytest.raises(InternalError):
        updater(f, exe).run()


def test_assets_outside_pinned_hosts_are_ignored(exe: Path) -> None:
    f = FakeFetcher()
    for a in f.release["assets"]:
        a["browser_download_url"] = "https://evil.example/" + a["name"]
    with pytest.raises(InternalError, match="missing"):
        updater(f, exe).run()


def test_symlinked_install_replaces_target(tmp_path: Path, exe: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(exe)
    updater(FakeFetcher(), link).run()
    assert link.is_symlink()
    assert exe.read_bytes() == b"NEW-BINARY"
    assert exe.with_name("Xtractor.bak").read_bytes() == b"OLD-BINARY"


def test_planted_staging_symlink_is_not_followed(tmp_path: Path, exe: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"KEEP")
    (exe.parent / ".Xtractor.new").symlink_to(victim)
    updater(FakeFetcher(), exe).run()
    assert victim.read_bytes() == b"KEEP"


def test_staged_file_removed_when_replace_fails(exe: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: object, dst: object) -> None:
        raise PermissionError(13, "nope")

    monkeypatch.setattr(selfupdate.os, "replace", boom)
    with pytest.raises(FileSystemError):
        updater(FakeFetcher(), exe).run()
    assert not [p for p in exe.parent.iterdir() if p.name.startswith(".")]


def test_override_repo_is_announced(exe: Path) -> None:
    logs: list[str] = []
    updater(FakeFetcher(), exe, log=logs.append).run()
    assert any("override" in m for m in logs)


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
    monkeypatch.setattr(
        "xtractor.selfupdate.run_self_update",
        lambda: (print("9.9.9"), 0)[1],  # stdout-ok
    )
    assert main(["--self-update"]) == 0


def test_help_and_version_never_touch_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    assert main(["--version"]) == 0
    assert main(["-h"]) == 0


# --- network hardening -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.example/x",
        "https://github.com.evil.example/x",
        "https://user@github.com/x",
        "ftp://github.com/x",
        "file:///etc/passwd",
    ],
)
def test_check_url_rejects(url: str) -> None:
    with pytest.raises(NetworkError):
        selfupdate.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com/repos/a/b/releases/latest",
        "https://github.com/a/b/releases/download/v1/x",
        "https://objects.githubusercontent.com/x",
        "https://release-assets.githubusercontent.com/x",
    ],
)
def test_check_url_accepts(url: str) -> None:
    selfupdate.check_url(url)


def test_redirect_handler_blocks_downgrade_and_foreign_hosts() -> None:
    import urllib.request
    from http.client import HTTPMessage

    handler = selfupdate._PinnedRedirects()
    req = urllib.request.Request(
        "https://api.github.com/x", headers={"Accept": "application/vnd.github+json"}
    )
    for target in ("http://objects.githubusercontent.com/x", "https://evil.example/x"):
        with pytest.raises(NetworkError):
            handler.redirect_request(req, io.BytesIO(), 302, "Found", HTTPMessage(), target)
    new = handler.redirect_request(
        req, io.BytesIO(), 302, "Found", HTTPMessage(), "https://objects.githubusercontent.com/x"
    )
    assert new is not None
    assert not new.has_header("Accept")


class _Resp:
    def __init__(self, chunks: list[bytes], length: str | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = {"Content-Length": length} if length else {}

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def _fetcher_with(monkeypatch: pytest.MonkeyPatch, resp: _Resp) -> selfupdate.UrllibFetcher:
    f = selfupdate.UrllibFetcher()
    monkeypatch.setattr(f, "_open", lambda url: resp)
    return f


def test_download_ok_and_size_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "d"
    _fetcher_with(monkeypatch, _Resp([b"abc", b"de"])).download("u", dest, 10)
    assert dest.read_bytes() == b"abcde"
    with pytest.raises(NetworkError, match="exceeded"):
        _fetcher_with(monkeypatch, _Resp([b"abc", b"de"])).download("u", dest, 4)
    with pytest.raises(NetworkError, match="larger"):
        _fetcher_with(monkeypatch, _Resp([b"a"], length="999")).download("u", dest, 10)


def test_download_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([0.0, 10_000.0, 20_000.0])
    monkeypatch.setattr(selfupdate.time, "monotonic", lambda: next(ticks))
    with pytest.raises(NetworkError, match="timed out"):
        _fetcher_with(monkeypatch, _Resp([b"a", b"b"])).download("u", tmp_path / "d", 10)


def test_get_json(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fetcher_with(monkeypatch, _Resp([b'{"a": 1}'])).get_json("u") == {"a": 1}


def test_open_pins_url_and_sets_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    class Opener:
        def open(self, req: Any, timeout: int) -> str:
            seen.append((req, timeout))
            return "resp"

    monkeypatch.setattr(selfupdate.urllib.request, "build_opener", lambda *h: Opener())
    f = selfupdate.UrllibFetcher()
    with pytest.raises(NetworkError):
        f._open("http://github.com/x")
    assert f._open("https://api.github.com/x") == "resp"
    assert seen[0][0].get_header("Accept") == "application/vnd.github+json"
    f._open("https://github.com/x")
    assert not seen[1][0].has_header("Accept")


# --- codesign / smoke test ---------------------------------------------------------------


def test_smoke_test_requires_exact_version(tmp_path: Path) -> None:
    script = tmp_path / "x"
    script.write_text("#!/bin/sh\necho 'Xtractor 1.0.10'\n")
    script.chmod(0o755)
    assert selfupdate.smoke_test(script, "1.0.10")
    assert not selfupdate.smoke_test(script, "1.0.1")
    assert not selfupdate.smoke_test(tmp_path / "missing", "1.0.10")


def test_adhoc_sign_uses_absolute_codesign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class P:
        def __init__(self, rc: int = 0, err: str = "") -> None:
            self.returncode, self.stderr = rc, err

    def fake_run(argv: list[str], **kw: Any) -> P:
        calls.append(argv)
        return P(err="Authority=Developer ID Application: X" if "-dv" in argv else "")

    monkeypatch.setattr(selfupdate.sys, "platform", "darwin")
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    selfupdate.adhoc_sign(tmp_path / "b")
    assert all(c[0] == "/usr/bin/codesign" for c in calls)
    assert "--verify" in calls[-1]  # Developer ID signature kept and verified
    calls.clear()
    monkeypatch.setattr(
        selfupdate.subprocess, "run", lambda argv, **kw: (calls.append(argv), P())[1]
    )
    selfupdate.adhoc_sign(tmp_path / "b")
    assert calls[-1][1:3] == ["--force", "-s"]


def test_adhoc_sign_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfupdate.sys, "platform", "darwin")

    class P:
        returncode, stderr = 1, "bad"

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(InternalError, match="codesign failed"):
        selfupdate.adhoc_sign(tmp_path / "b")

    def oserr(*a: object, **k: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(selfupdate.subprocess, "run", oserr)
    with pytest.raises(InternalError, match="could not run"):
        selfupdate.adhoc_sign(tmp_path / "b")
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    selfupdate.adhoc_sign(tmp_path / "b")  # no-op off macOS


def test_run_self_update_prints_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], exe: Path
) -> None:
    monkeypatch.setattr(selfupdate.sys, "frozen", True, raising=False)
    monkeypatch.setattr(selfupdate.sys, "executable", str(exe))
    monkeypatch.delenv(selfupdate.REPO_ENV, raising=False)
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")  # adhoc_sign becomes a no-op
    fetcher = FakeFetcher(tar=make_tar(b"#!/bin/sh\necho 'Xtractor 1.2.0'\n"))
    assert selfupdate.run_self_update(fetcher) == 0
    assert capsys.readouterr().out.strip() == NEW


def test_trusted_key_is_valid_hex() -> None:
    import importlib

    mod = importlib.reload(selfupdate)
    assert mod.TRUSTED_PUBLIC_KEYS
    for k in mod.TRUSTED_PUBLIC_KEYS:
        assert len(bytes.fromhex(k)) == 32
