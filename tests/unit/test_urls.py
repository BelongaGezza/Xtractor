from __future__ import annotations

import pytest

from xtractor.errors import UsageError
from xtractor.urls import parse_youtube_url

VID = "dQw4w9WgXcQ"
CANON = f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"http://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://music.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?t=10",
        f"https://youtu.be/{VID}?si=abcdef",
        f"https://youtu.be/{VID}/",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://youtube.com/shorts/{VID}?feature=share",
        f"https://www.youtube.com/live/{VID}",
        f"https://www.youtube.com/live/{VID}?si=xyz",
        f"https://www.youtube.com/watch?v={VID}&t=30s",
        f"https://www.youtube.com/watch?v={VID}&utm_source=x&utm_medium=y&feature=share&pp=abc",
        f"https://www.youtube.com/watch?feature=share&v={VID}",
        f"https://WWW.YouTube.com/watch?v={VID}",
        f"https://www.youtube.com/watch?v={VID}#t=10",
        f"  https://youtu.be/{VID}  ",
        f"www.youtube.com/watch?v={VID}",
        f"youtu.be/{VID}",
        f"https://www.youtube.com/watch?v={VID}&list=PLabc&index=3",
        f"https://youtu.be/{VID}?list=PLabc",
    ],
)
def test_valid(url: str) -> None:
    ref = parse_youtube_url(url)
    assert ref.video_id == VID
    assert ref.canonical_url == CANON


def test_playlist_param_is_flagged_and_stripped() -> None:
    ref = parse_youtube_url(f"https://www.youtube.com/watch?v={VID}&list=PLabc&index=3&si=q")
    assert ref.had_playlist_param
    assert "list" not in ref.canonical_url
    assert not parse_youtube_url(f"https://youtu.be/{VID}").had_playlist_param


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not a url",
        "https://vimeo.com/12345",
        f"https://youtube.com.evil.com/watch?v={VID}",
        f"https://evil.com/youtube.com/watch?v={VID}",
        f"https://notyoutube.com/watch?v={VID}",
        f"https://youtube.com@evil.com/watch?v={VID}",
        f"https://user:pw@www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com:8080/watch?v={VID}",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=toolongvideoid123",
        "https://youtu.be/short",
        "https://youtu.be/",
        f"https://youtu.be/{VID}/extra",
        "https://www.youtube.com/",
        "https://www.youtube.com/feed/subscriptions",
        f"ftp://www.youtube.com/watch?v={VID}",
        "javascript:alert(1)",
        f"file:///etc/passwd?v={VID}",
        "https://www.youtube.com/shorts/",
        "https://www.youtube.com/shorts/bad",
        "https://",
        "http://[::1",
    ],
)
def test_invalid(url: str) -> None:
    with pytest.raises(UsageError):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PLabcdef",
        "https://www.youtube.com/watch?list=PLabcdef",
    ],
)
def test_bare_playlist(url: str) -> None:
    with pytest.raises(UsageError, match="playlists are not supported in v1"):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/channel/UCabc",
        "https://www.youtube.com/@somehandle",
        "https://www.youtube.com/c/Name",
        "https://www.youtube.com/user/Name",
    ],
)
def test_channels(url: str) -> None:
    with pytest.raises(UsageError, match="channels are not supported"):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%0A",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%0a",
        "https://youtu.be/dQw4w9WgXcQ%0A",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ%0A",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%00",
    ],
)
def test_trailing_newline_in_video_id_is_rejected(url: str) -> None:
    with pytest.raises(UsageError):
        parse_youtube_url(url)
