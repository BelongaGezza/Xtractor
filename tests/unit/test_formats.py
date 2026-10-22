from __future__ import annotations

import pytest

from tests.unit.fixtures import (
    AAC_441,
    AAC_480,
    AV1_2160,
    AVC,
    MUXED_18,
    OPUS,
    OPUS_LOW,
    VP9,
    aud,
    media,
    standard_formats,
    vid,
)
from xtractor.errors import FormatUnavailable, VideoUnavailable
from xtractor.formats import (
    FormatInfo,
    MediaInfo,
    Tags,
    check_playable,
    select_audio,
    select_video,
)
from xtractor.options import AudioOptions, VideoOptions


def A(fmt: str = "m4a", rate: int = 44100, br: str | None = None) -> AudioOptions:
    return AudioOptions(rate, fmt, br)  # type: ignore[arg-type]


def V(h: int | None = 1080, fmt: str = "mp4", strict: bool = False) -> VideoOptions:
    return VideoOptions(h, fmt, strict)  # type: ignore[arg-type]


# ------------------------------------------------------------ models
def test_from_dict_roundtrip() -> None:
    info = MediaInfo.from_dict(
        {
            "id": "abc",
            "title": "T",
            "channel": "Chan",
            "upload_date": "20240131",
            "live_status": "not_live",
            "formats": [
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "asr": 44100,
                    "abr": 129.5,
                    "filesize_approx": 10,
                },
                {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none", "height": 1080},
                {"format_id": "x", "vcodec": None, "acodec": None, "abr": True, "has_drm": True},
            ],
        }
    )
    f140, f137, fx = info.formats
    assert f140.audio_only and f140.is_aac and f140.filesize == 10
    assert f137.video_only and f137.vfamily == "avc1"
    assert not fx.has_audio and not fx.has_video and fx.has_drm and fx.abr is None
    assert info.uploader == "Chan"
    tags = Tags.from_media(info, "https://u")
    assert (tags.title, tags.artist, tags.date, tags.url) == (
        "T",
        "Chan",
        "2024-01-31",
        "https://u",
    )
    assert Tags.from_media(MediaInfo(id="x", title="")).date is None


def test_vfamily() -> None:
    assert vid("a", 1, "vp09.00").vfamily == "vp9"
    assert vid("a", 1, "av01.0").vfamily == "av1"
    assert vid("a", 1, "h264").vfamily == "avc1"
    assert vid("a", 1, "theora").vfamily == "other"


# ------------------------------------------------------------ playable
def test_check_playable() -> None:
    check_playable(media(standard_formats()))
    for kw in ({"is_live": True}, {"live_status": "is_upcoming"}, {"live_status": "post_live"}):
        with pytest.raises(VideoUnavailable, match="live"):
            check_playable(media(standard_formats(), **kw))
    with pytest.raises(VideoUnavailable, match="DRM"):
        check_playable(media([aud("1", "m4a", "mp4a.40.2", 44100, 128, drm=True)]))
    with pytest.raises(VideoUnavailable, match="no downloadable"):
        check_playable(media([]))


# ------------------------------------------------------------ audio
def test_ac3_default_copies_44k_aac() -> None:
    plan = select_audio(standard_formats(), A())
    assert plan.format_id == "140"
    assert plan.copy and plan.ext == "m4a"
    assert plan.ffmpeg_codec_args == ("-c:a", "copy", "-movflags", "+faststart")
    assert plan.notices == ()


def test_m4a_prefers_matching_rate_over_other_aac() -> None:
    plan = select_audio([AAC_480, AAC_441, OPUS], A())
    assert plan.format_id == "140" and plan.copy


def test_s2_48k_only_aac_transcodes_with_notice() -> None:
    plan = select_audio([AAC_480, OPUS], A())
    assert not plan.copy
    assert plan.format_id == "140-48"
    assert plan.ffmpeg_codec_args == ("-c:a", "aac", "-b:a", "128k", "-ar", "44100")
    assert "48000 Hz" in plan.notices[0]


def test_s1_explicit_bitrate_forces_transcode() -> None:
    plan = select_audio(standard_formats(), A(br="192k"))
    assert not plan.copy
    assert plan.format_id == "140"
    assert plan.ffmpeg_codec_args == ("-c:a", "aac", "-b:a", "192k", "-ar", "44100")
    assert plan.notices == ()


def test_m4a_with_opus_only_source() -> None:
    plan = select_audio([OPUS, OPUS_LOW], A())
    assert plan.format_id == "251" and not plan.copy
    assert plan.ffmpeg_codec_args[:2] == ("-c:a", "aac")
    assert any("AAC" in n for n in plan.notices) or any("48000" in n for n in plan.notices)


def test_ac4_wav_48k() -> None:
    plan = select_audio(standard_formats(), A("wav", 48000))
    assert plan.ext == "wav" and not plan.copy
    assert plan.ffmpeg_codec_args == ("-c:a", "pcm_s16le", "-ar", "48000")
    assert plan.format_id == "251"  # opus 135 > aac 129.5
    assert plan.notices == ()


def test_opus_copy_and_transcode() -> None:
    plan = select_audio(standard_formats(), A("opus", 48000))
    assert plan.copy and plan.ext == "opus" and plan.format_id == "251"
    assert plan.ffmpeg_codec_args == ("-c:a", "copy")
    plan = select_audio(standard_formats(), A("opus", 48000, "96k"))
    assert not plan.copy
    assert plan.ffmpeg_codec_args == ("-c:a", "libopus", "-b:a", "96k", "-ar", "48000")
    plan = select_audio([AAC_441], A("opus", 48000))
    assert not plan.copy and plan.format_id == "140" and plan.notices


def test_mp3_flac() -> None:
    plan = select_audio(standard_formats(), A("mp3", 44100, "320k"))
    assert plan.ffmpeg_codec_args == ("-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100")
    assert plan.ext == "mp3"
    assert "resampling 48000 Hz -> 44100 Hz" in plan.notices
    plan = select_audio([AAC_441], A("mp3"))
    assert plan.ffmpeg_codec_args[3] == "128k" and plan.notices == ()
    plan = select_audio(standard_formats(), A("flac", 48000))
    assert plan.ffmpeg_codec_args == ("-c:a", "flac", "-ar", "48000")
    assert any("lossy" in n for n in plan.notices)


def test_audio_ignores_drm_and_video() -> None:
    drm = aud("9", "m4a", "mp4a.40.2", 44100, 999, drm=True)
    assert select_audio([drm, AAC_441, AVC[720]], A()).format_id == "140"
    with pytest.raises(VideoUnavailable):
        select_audio([drm, AVC[720]], A())


# ------------------------------------------------------------ video
def test_ac6_default_mp4_avc_1080() -> None:
    plan = select_video(standard_formats(), V())
    assert plan.container == "mp4"
    assert plan.format_selector == "avc1080+140"
    assert plan.height == 1080 and plan.notices == ()


def test_mp4_resolution_picks_highest_not_above() -> None:
    plan = select_video(standard_formats(), V(720))
    assert plan.video_format_id == "avc720" and plan.notices == ()


def test_mp4_height_fallback_notice() -> None:
    fmts = [AAC_441, AVC[360], AVC[480], VP9[720]]
    plan = select_video(fmts, V(720))
    assert plan.video_format_id == "avc480"
    assert plan.notices == ("720p unavailable for mp4/H.264, using 480p",)


def test_request_above_max_uses_max_with_notice() -> None:
    fmts = [AAC_441, AVC[720], AVC[1080]]
    plan = select_video(fmts, V(1440))
    assert plan.container == "mp4" and plan.height == 1080
    assert "1440p unavailable" in plan.notices[0]
    plan = select_video(fmts, V(None))
    assert plan.container == "mp4" and plan.notices == ()


def test_ac7_2160_switches_to_mkv() -> None:
    plan = select_video(standard_formats(), V(2160))
    assert plan.container == "mkv"
    assert plan.height == 2160
    assert plan.video_format_id == "vp9-2160"  # vp9 beats av1 on ties
    assert plan.audio_format_id == "251"  # best audio overall
    assert plan.notices == ("container switched mp4 -> mkv (VP9/AV1 required for >1080p)",)
    assert select_video(standard_formats(), V(None)).container == "mkv"


def test_ac7_strict_raises_exit_6() -> None:
    with pytest.raises(FormatUnavailable) as info:
        select_video(standard_formats(), V(2160, strict=True))
    assert info.value.exit_code == 6


def test_mp4_ceiling_1440_picks_1440() -> None:
    plan = select_video(standard_formats(), V(1440))
    assert plan.container == "mkv" and plan.height == 1440


def test_no_avc_at_all_mp4() -> None:
    fmts = [AAC_441, OPUS, VP9[720], VP9[1080]]
    plan = select_video(fmts, V(1080))
    assert plan.container == "mkv" and plan.video_format_id == "vp9-1080"
    assert "no H.264/AAC" in plan.notices[0]
    with pytest.raises(FormatUnavailable):
        select_video(fmts, V(1080, strict=True))


def test_mp4_without_aac_audio_switches() -> None:
    plan = select_video([OPUS, AVC[720]], V(720))
    assert plan.container == "mkv" and plan.audio_format_id == "251"


def test_720_max_source() -> None:
    fmts = [AAC_441, AVC[360], AVC[480], AVC[720]]
    plan = select_video(fmts, V(1080))
    assert plan.video_format_id == "avc720"
    assert plan.notices == ("1080p unavailable for mp4/H.264, using 720p",)


def test_fps_and_tbr_tiebreaks() -> None:
    a = vid("a", 1080, "avc1.x", fps=30, tbr=3000)
    b = vid("b", 1080, "avc1.x", fps=60, tbr=2000)
    c = vid("c", 1080, "avc1.x", fps=60, tbr=2500)
    assert select_video([AAC_441, a, b, c], V()).video_format_id == "c"


def test_mkv_requested() -> None:
    plan = select_video(standard_formats(), V(1080, "mkv"))
    assert plan.container == "mkv" and plan.video_format_id == "avc1080"  # avc preferred <=1080
    plan = select_video(standard_formats(), V(2160, "mkv"))
    assert plan.video_format_id == "vp9-2160" and plan.notices == ()
    plan = select_video(standard_formats(), V(1440, "mkv", strict=True))
    assert plan.container == "mkv"
    plan = select_video([AAC_441, AVC[360]], V(720, "mkv"))
    assert "720p unavailable for mkv, using 360p" in plan.notices


def test_webm_requested() -> None:
    plan = select_video(standard_formats(), V(1080, "webm"))
    assert plan.container == "webm"
    assert plan.video_format_id == "vp9-1080" and plan.audio_format_id == "251"
    assert plan.format_selector == "vp9-1080+251"
    plan = select_video([*standard_formats(), AV1_2160], V(None, "webm"))
    assert plan.video_format_id == "vp9-2160"


def test_webm_fallbacks() -> None:
    fmts = [AAC_441, AVC[720]]
    plan = select_video(fmts, V(720, "webm"))
    assert plan.container == "mkv"
    assert plan.notices == ("container switched webm -> mkv (no VP9/AV1 + Opus streams available)",)
    with pytest.raises(FormatUnavailable):
        select_video(fmts, V(720, "webm", strict=True))
    # VP9 present but no opus audio
    with pytest.raises(FormatUnavailable):
        select_video([AAC_441, VP9[720]], V(720, "webm", strict=True))


def test_nothing_at_or_below_limit() -> None:
    fmts = [AAC_441, AVC[720], AVC[1080]]
    plan = select_video(fmts, V(360))
    assert plan.video_format_id == "avc720"
    assert "lowest available (720p)" in plan.notices[0]
    with pytest.raises(FormatUnavailable):
        select_video(fmts, V(360, strict=True))


def test_muxed_fallback() -> None:
    plan = select_video([MUXED_18, STORYBOARD_ONLY], V())
    assert plan.format_selector == "18" and plan.container == "mp4"
    assert plan.audio_format_id is None
    assert "360p" in plan.notices[0]
    plan = select_video([MUXED_18], V(720, "mkv"))
    assert plan.container == "mp4" and "not mkv" in plan.notices[-1]
    with pytest.raises(FormatUnavailable):
        select_video([MUXED_18], V(720, "mkv", strict=True))
    with pytest.raises(VideoUnavailable):
        select_video([STORYBOARD_ONLY], V())
    plan = select_video([MUXED_18], V(144))
    assert plan.height == 360


def test_video_ignores_drm() -> None:
    drm = FormatInfo("d", "mp4", "avc1.x", "none", height=1080, has_drm=True)
    plan = select_video([AAC_441, drm, AVC[720]], V())
    assert plan.video_format_id == "avc720"


STORYBOARD_ONLY = FormatInfo(format_id="sb0", ext="mhtml", height=90)


def test_from_dict_uses_nominal_rung_for_letterboxed_video() -> None:
    """Live finding: a 1080p rung of a 2.39:1 film reports height=818 but note '1080p'."""
    from xtractor.formats import FormatInfo

    f = FormatInfo.from_dict({"format_id": "137", "height": 818, "format_note": "1080p"})
    assert f.height == 1080
    assert (
        FormatInfo.from_dict({"format_id": "x", "height": 720, "format_note": "720p60"}).height
        == 720
    )
    assert FormatInfo.from_dict({"format_id": "x", "height": 546}).height == 546
    assert (
        FormatInfo.from_dict({"format_id": "x", "height": 546, "format_note": "low"}).height == 546
    )


# ------------------------------------------------------------ DRC variants
def test_is_drc_detection() -> None:
    from tests.unit.fixtures import AAC_441_DRC

    assert AAC_441_DRC.is_drc
    assert FormatInfo(format_id="251-DRC").is_drc
    assert FormatInfo(format_id="x", note="medium, drc").is_drc
    assert FormatInfo(format_id="x", label="x - audio only (low, DRC)").is_drc
    assert not AAC_441.is_drc
    d = {"format_id": "140-drc", "format": "140-drc - audio only (medium, DRC)", "acodec": "x"}
    assert FormatInfo.from_dict(d).is_drc


def test_drc_never_preferred_even_with_higher_bitrate() -> None:
    from tests.unit.fixtures import AAC_441_DRC

    fmts = [AAC_441_DRC, *standard_formats()]
    assert select_audio(fmts, A()).format_id == "140"
    assert select_audio(fmts[::-1], A()).format_id == "140"
    assert select_audio(fmts, A(br="192k")).format_id == "140"
    assert select_audio(fmts, A("wav")).format_id == "251"


def test_drc_used_only_as_last_resort() -> None:
    from tests.unit.fixtures import AAC_441_DRC

    plan = select_audio([AAC_441_DRC], A())
    assert plan.format_id == "140-drc" and plan.copy
