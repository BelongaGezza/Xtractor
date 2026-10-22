"""``Xtractor --self-update``: check the latest GitHub release, verify, swap the binary.

Design (spec F13/section 9, plan R14): HTTPS to the GitHub releases API only when the user
asks; the tarball is verified against the release's ``SHA256SUMS``; the new binary is staged
beside the running one, ad-hoc signed and smoke-tested, then swapped in with ``os.replace``.
The previous binary is kept as ``<name>.bak`` and restored if the post-swap check fails.
All network access goes through the injectable :class:`Fetcher`.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import __version__
from .errors import (
    EXIT_OK,
    FileSystemError,
    InternalError,
    NetworkError,
    UsageError,
)

#: Where releases are fetched from; override with XTRACTOR_UPDATE_REPO=owner/repo.
DEFAULT_REPO = "BelongaGezza/Xtractor"
REPO_ENV = "XTRACTOR_UPDATE_REPO"
BINARY_NAME = "Xtractor"
SUMS_NAME = "SHA256SUMS"
PIPX_HINT = "this is not a standalone binary install; update with: pipx upgrade Xtractor"
BREW_HINT = "Xtractor is managed by Homebrew; update with: brew upgrade xtractor"
USER_AGENT = f"Xtractor/{__version__} (+self-update)"
TIMEOUT_S = 30
MAX_BINARY_BYTES = 1024 * 1024 * 1024

_REPO_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|a|b|rc|pre)[.-]?(\d*))?$", re.IGNORECASE
)
_PRE_RANK = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "pre": 1, "rc": 2}

VersionKey = tuple[int, int, int, int, int, int]


def parse_version(text: str) -> VersionKey:
    """Return a sortable key; ``1.0.0-rc.1`` < ``1.0.0``. Accepts a leading ``v`` and PEP 440 rc."""
    m = _VERSION_RE.match(text.strip())
    if not m:
        raise InternalError(f"cannot parse version {text!r}")
    major, minor, patch = int(m[1]), int(m[2]), int(m[3])
    if m[4] is None:
        return (major, minor, patch, 1, 0, 0)
    return (major, minor, patch, 0, _PRE_RANK[m[4].lower()], int(m[5] or 0))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


class Fetcher(Protocol):
    """Network seam. Implementations raise urllib/OSError-style errors; they are mapped here."""

    def get_json(self, url: str) -> Any: ...

    def download(self, url: str, dest: Path) -> None: ...


class UrllibFetcher:
    """Real HTTPS fetcher (stdlib only)."""

    def _open(self, url: str) -> Any:
        if not url.startswith("https://"):
            raise NetworkError(f"refusing non-HTTPS URL: {url}")
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        )
        return urllib.request.urlopen(req, timeout=TIMEOUT_S)

    def get_json(self, url: str) -> Any:
        with self._open(url) as resp:
            return json.loads(resp.read(10 * 1024 * 1024))

    def download(self, url: str, dest: Path) -> None:
        with self._open(url) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)


_NET_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException)


def _net(action: str, fn: Callable[[], Any]) -> Any:
    """Run a fetcher call, mapping network failures to :class:`NetworkError` (exit 4)."""
    try:
        return fn()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NetworkError(f"{action}: not found (HTTP 404)") from exc
        if exc.code in (403, 429):
            raise NetworkError(
                f"{action}: GitHub refused the request (HTTP {exc.code}, rate limit?); "
                "try again later"
            ) from exc
        raise NetworkError(f"{action}: HTTP {exc.code}") from exc
    except _NET_ERRORS as exc:
        reason = getattr(exc, "reason", exc)
        raise NetworkError(f"{action}: {reason}; check your internet connection") from exc
    except json.JSONDecodeError as exc:
        raise NetworkError(f"{action}: unreadable response from GitHub") from exc


def resolve_repo(env: dict[str, str] | None = None) -> str:
    repo = (os.environ if env is None else env).get(REPO_ENV) or DEFAULT_REPO
    if repo.startswith("OWNER/"):
        raise UsageError(
            "the update repository is not configured in this build",
            hint=f"set {REPO_ENV}=owner/repo to choose where releases are fetched from",
        )
    if not _REPO_RE.match(repo):
        raise UsageError(f"invalid {REPO_ENV} value {repo!r}; expected owner/repo")
    return repo


def is_homebrew_path(path: Path) -> bool:
    parts = {str(path), str(path.resolve())}
    return any("/Cellar/" in p or "/Homebrew/" in p for p in parts)


def parse_sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum``-style output into ``{filename: hexdigest}``."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[Path(m[2]).name] = m[1].lower()
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_binary(tarball: Path, dest: Path) -> None:
    """Copy the ``Xtractor`` regular file out of the tarball (no ``extractall``)."""
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            for member in tf:
                if member.isfile() and Path(member.name).name == BINARY_NAME:
                    if member.size <= 0 or member.size > MAX_BINARY_BYTES:
                        raise InternalError("release archive contains an implausible binary")
                    src = tf.extractfile(member)
                    if src is None:
                        break
                    with src, dest.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    dest.chmod(0o755)
                    return
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        raise InternalError(f"release archive is corrupt: {exc}") from exc
    raise InternalError(f"release archive does not contain {BINARY_NAME}")


def adhoc_sign(path: Path) -> None:
    """``codesign --force -s -`` (macOS only; arm64 requires at least an ad-hoc signature)."""
    if sys.platform != "darwin":
        return
    try:
        proc = subprocess.run(
            ["codesign", "--force", "-s", "-", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError(f"could not run codesign: {exc}") from exc
    if proc.returncode != 0:
        raise InternalError(f"codesign failed: {proc.stderr.strip() or proc.returncode}")


def smoke_test(path: Path, expected_version: str) -> bool:
    """Run ``<path> --version``; True when it exits 0 and mentions the expected version."""
    try:
        proc = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and expected_version in proc.stdout


@dataclass
class SelfUpdater:
    """Everything injectable for tests; defaults are the real thing."""

    fetcher: Fetcher
    current_version: str = __version__
    executable: Path | None = None
    frozen: bool | None = None
    repo: str | None = None
    signer: Callable[[Path], None] = adhoc_sign
    verifier: Callable[[Path, str], bool] = smoke_test
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr)

    def run(self) -> str:
        """Perform the update. Returns the version now installed. Raises XtractorError."""
        is_frozen = getattr(sys, "frozen", False) if self.frozen is None else self.frozen
        if not is_frozen:
            raise UsageError(PIPX_HINT)
        exe = self.executable if self.executable is not None else Path(sys.executable)
        if is_homebrew_path(exe):
            raise UsageError(BREW_HINT)
        repo = self.repo if self.repo is not None else resolve_repo()

        release = _net(
            "checking for updates",
            lambda: self.fetcher.get_json(f"https://api.github.com/repos/{repo}/releases/latest"),
        )
        tag, assets = _read_release(release)
        if not is_newer(tag, self.current_version):
            self.log(f"Xtractor {self.current_version} is already up to date")
            return self.current_version
        version = tag.lstrip("v")
        tar_name = f"{BINARY_NAME}-{version}-macos-arm64.tar.gz"
        if tar_name not in assets or SUMS_NAME not in assets:
            raise InternalError(f"release {tag} is missing {tar_name} or {SUMS_NAME}")

        exe_dir = exe.parent
        if not os.access(exe_dir, os.W_OK):
            raise FileSystemError(
                f"cannot write to {exe_dir}", hint="re-run with sufficient permissions"
            )
        self.log(f"Updating Xtractor {self.current_version} -> {version}")
        try:
            work = Path(tempfile.mkdtemp(prefix=".xtractor-update-", dir=exe_dir))
        except OSError as exc:
            raise FileSystemError(f"cannot create a staging directory in {exe_dir}: {exc}") from exc
        try:
            self._install(exe, work, assets, tar_name, version)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return version

    def _install(
        self, exe: Path, work: Path, assets: dict[str, str], tar_name: str, version: str
    ) -> None:
        tarball, sums = work / tar_name, work / SUMS_NAME
        _net("downloading checksums", lambda: self.fetcher.download(assets[SUMS_NAME], sums))
        _net("downloading release", lambda: self.fetcher.download(assets[tar_name], tarball))
        expected = parse_sums(sums.read_text(errors="replace")).get(tar_name)
        if expected is None:
            raise InternalError(f"{SUMS_NAME} has no entry for {tar_name}")
        actual = sha256_file(tarball)
        if actual != expected:
            raise InternalError(
                f"checksum mismatch for {tar_name}; the installed binary was not changed"
            )

        new = work / BINARY_NAME
        extract_binary(tarball, new)
        self.signer(new)
        if not self.verifier(new, version):
            raise InternalError("the downloaded binary failed its self-check; not installing it")

        backup = exe.with_name(exe.name + ".bak")
        try:
            with contextlib.suppress(FileNotFoundError):
                backup.unlink()
            try:
                os.link(exe, backup)  # keeps the old inode alive; no gap with no binary
            except OSError:
                shutil.copy2(exe, backup)
            staged = exe.with_name(f".{exe.name}.new")
            shutil.copy2(new, staged)
            os.replace(staged, exe)
        except OSError as exc:
            raise FileSystemError(f"could not replace {exe}: {exc.strerror or exc}") from exc

        if not self.verifier(exe, version):
            try:
                os.replace(backup, exe)
            except OSError as exc:
                raise InternalError(
                    f"update failed and rollback failed ({exc}); restore from {backup}"
                ) from exc
            raise InternalError("the updated binary failed verification; rolled back")
        self.log(f"Previous version kept at {backup}")


def _read_release(release: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(release, dict) or not isinstance(release.get("tag_name"), str):
        raise InternalError("unexpected response from the GitHub releases API")
    assets: dict[str, str] = {}
    for a in release.get("assets") or []:
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            url = a.get("browser_download_url")
            if isinstance(url, str) and url.startswith("https://"):
                assets[a["name"]] = url
    return release["tag_name"], assets


def run_self_update(fetcher: Fetcher | None = None) -> int:
    """CLI entry: returns the exit code, raising :class:`XtractorError` on failure."""
    version = SelfUpdater(fetcher=fetcher or UrllibFetcher()).run()
    print(version)  # stdout-ok
    return EXIT_OK
