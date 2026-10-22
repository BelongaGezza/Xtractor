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


def test_bot_check_has_its_own_accurate_message_and_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    msg = "ERROR: [youtube] abc: Sign in to confirm you're not a bot"
    err = E.classify_exception(ExtractorError(msg), video_id="abc")
    assert err.exit_code == 3
    assert "not a bot" in str(err) and "[abc]" in str(err)
    assert "video unavailable" not in str(err)  # it is not a statement about the video
    assert "pipx upgrade Xtractor" in str(err)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    frozen = E.classify_exception(ExtractorError(msg), video_id="abc")
    assert "Xtractor --self-update" in str(frozen) and "pipx" not in str(frozen)


def test_update_hint_depends_on_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    assert E.update_hint() == E.UPDATE_HINT_SOURCE
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert E.update_hint() == E.UPDATE_HINT_BINARY and "--self-update" in E.update_hint()
    err = E.classify_exception(
        ExtractorError("ERROR: [youtube] abc: Unable to extract initial player response")
    )
    assert err.exit_code == 1 and "Xtractor --self-update" in str(err)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (ValueError("deno is not a known thing"), 1),
        (RuntimeError("no node found in tree"), 1),
        (ExtractorError("ERROR: [youtube] abc: the node.js of this is not matching"), 1),
        (ExtractorError("ERROR: [youtube] abc: No supported JavaScript runtime could be found"), 5),
        (
            ExtractorError("ERROR: [youtube] abc: JavaScript runtime required to solve challenge"),
            5,
        ),
    ],
)
def test_js_runtime_classifier_is_narrow(exc: Exception, code: int) -> None:
    assert E.classify_exception(exc).exit_code == code


def test_http_403_is_a_stale_extractor_symptom_not_a_network_error() -> None:
    err = E.classify_exception(
        ExtractorError("ERROR: unable to download video data: HTTP Error 403: Forbidden"),
        video_id="abc",
    )
    assert err.exit_code == 1 and "out of date" in str(err) and "pipx upgrade" in str(err)


@pytest.mark.parametrize(
    "msg",
    [
        "ERROR: [youtube] abc: Requested format is not available. Use --list-formats",
        "ERROR: [youtube] abc: This video requires payment to watch",
        "ERROR: [youtube] abc: The following content is not available on this app.",
        "ERROR: [youtube] abc: Offline.",
    ],
)
def test_more_unavailable_phrases_are_exit_3(msg: str) -> None:
    assert E.classify_exception(ExtractorError(msg), video_id="abc").exit_code == 3


@pytest.mark.parametrize("code", [errno.EEXIST, errno.ENOTDIR, errno.EISDIR])
def test_more_fs_errnos_are_exit_7(code: int) -> None:
    err = E.classify_exception(OSError(code, "nope", "/x"))
    assert err.exit_code == 7
    assert E.classify_exception(FileExistsError(errno.EEXIST, "exists", "/x")).exit_code == 7
