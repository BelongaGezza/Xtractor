from __future__ import annotations

import errno

import pytest

from xtractor import errors as E


class DownloadError(Exception):
    def __init__(self, msg: str, exc_info: tuple[object, ...] | None = None) -> None:
        super().__init__(msg)
        self.exc_info = exc_info


class ExtractorError(DownloadError):
    pass


class TransportError(OSError):
    pass


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (E.InternalError, 1),
        (E.UsageError, 2),
        (E.VideoUnavailable, 3),
        (E.NetworkError, 4),
        (E.MissingDependency, 5),
        (E.FormatUnavailable, 6),
        (E.FileSystemError, 7),
        (E.Interrupted, 130),
    ],
)
def test_exit_codes(cls: type[E.XtractorError], code: int) -> None:
    assert cls("x").exit_code == code
    assert code in dict(E.EXIT_CODE_TABLE)


def test_str_includes_hint() -> None:
    assert str(E.UsageError("bad", hint="try x")) == "bad (try x)"
    assert str(E.UsageError("bad")) == "bad"


@pytest.mark.parametrize(
    ("msg", "code"),
    [
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", 3),
        ("ERROR: [youtube] abc: Video unavailable", 3),
        ("ERROR: [youtube] abc: The uploader has not made this video available in your country", 3),
        ("ERROR: [youtube] abc: Sign in to confirm your age", 3),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", 3),
        ("ERROR: [youtube] abc: This video is DRM protected", 3),
        ("ERROR: [youtube] abc: This live event will begin in 2 hours", 3),
        ("ERROR: unable to download video data: HTTP Error 503: Service Unavailable", 4),
        ("ERROR: unable to download video data: HTTP Error 429: Too Many Requests", 4),
        ("ERROR: [youtube] abc: Unable to download webpage: <urlopen error timed out>", 4),
        ("ERROR: [youtube] abc: Unable to extract initial player response", 1),
        ("ERROR: [youtube] abc: No supported JavaScript runtime could be found", 5),
    ],
)
def test_ytdlp_messages(msg: str, code: int) -> None:
    err = E.classify_exception(ExtractorError(msg), video_id="abc")
    assert err.exit_code == code
    if code == 1:
        assert "pipx upgrade Xtractor" in str(err)
    if code == 3:
        assert "abc" in str(err)
        assert "ERROR:" not in str(err)


def test_wrapped_exc_info_is_inspected() -> None:
    inner = TransportError("boom")
    err = E.classify_exception(DownloadError("ERROR: something", (type(inner), inner, None)))
    assert err.exit_code == 4


@pytest.mark.parametrize(
    "exc",
    [TransportError("x"), ConnectionResetError("x"), TimeoutError("t"), ConnectionError("c")],
)
def test_network_types(exc: BaseException) -> None:
    assert E.classify_exception(exc).exit_code == 4


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES, errno.EROFS, errno.ENAMETOOLONG])
def test_filesystem(code: int) -> None:
    exc = OSError(code, "disk problem", "/x/y")
    err = E.classify_exception(exc)
    assert err.exit_code == 7
    assert "/x/y" in str(err)


def test_other_oserror_is_internal() -> None:
    assert E.classify_exception(OSError(errno.EIO, "io")).exit_code == 1


def test_missing_ffmpeg() -> None:
    exc = FileNotFoundError(errno.ENOENT, "No such file", "ffmpeg")
    assert E.classify_exception(exc).exit_code == 5
    assert E.classify_exception(RuntimeError("Unknown encoder 'libmp3lame'")).exit_code == 5


def test_passthrough_and_interrupt_and_default() -> None:
    original = E.FormatUnavailable("x")
    assert E.classify_exception(original) is original
    assert E.classify_exception(KeyboardInterrupt()).exit_code == 130
    err = E.classify_exception(ValueError("weird"))
    assert err.exit_code == 1
    assert "ValueError" in str(err)


@pytest.mark.parametrize(
    ("platform", "needle"),
    [("darwin", "brew install ffmpeg"), ("linux", "apt"), ("win32", "winget")],
)
def test_install_hint(platform: str, needle: str) -> None:
    assert needle in E.ffmpeg_install_hint(platform)
