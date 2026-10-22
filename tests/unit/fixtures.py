"""Hand-made format fixtures modelled on what yt-dlp exposes for YouTube."""

from __future__ import annotations

from xtractor.formats import FormatInfo, MediaInfo


def aud(fid: str, ext: str, codec: str, asr: int, abr: float, drm: bool = False) -> FormatInfo:
    return FormatInfo(
        format_id=fid, ext=ext, vcodec="none", acodec=codec, asr=asr, abr=abr, has_drm=drm
    )


def vid(
    fid: str, height: int, codec: str, fps: float = 30, tbr: float = 1000, ext: str = "mp4"
) -> FormatInfo:
    return FormatInfo(
        format_id=fid, ext=ext, vcodec=codec, acodec="none", height=height, fps=fps, tbr=tbr
    )


AAC_441 = aud("140", "m4a", "mp4a.40.2", 44100, 129.5)
AAC_480 = aud("140-48", "m4a", "mp4a.40.2", 48000, 129.5)
OPUS = aud("251", "webm", "opus", 48000, 135.0)
OPUS_LOW = aud("249", "webm", "opus", 48000, 50.0)

AVC = {h: vid(f"avc{h}", h, "avc1.640028", tbr=h * 2.0) for h in (360, 480, 720, 1080)}
VP9 = {
    h: vid(f"vp9-{h}", h, "vp09.00.40.08", tbr=h * 1.5, ext="webm")
    for h in (360, 480, 720, 1080, 1440, 2160)
}
AV1_2160 = vid("av1-2160", 2160, "av01.0.12M.08", tbr=2500, ext="mp4")
MUXED_18 = FormatInfo(
    format_id="18", ext="mp4", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360, tbr=500
)

STORYBOARD = FormatInfo(format_id="sb0", ext="mhtml", vcodec="none", acodec="none", height=90)


def standard_formats() -> list[FormatInfo]:
    """44.1k AAC + opus audio; avc1 to 1080 and VP9 to 2160, plus storyboard noise."""
    return [STORYBOARD, AAC_441, OPUS, OPUS_LOW, *AVC.values(), *VP9.values(), AV1_2160]


def media(formats: list[FormatInfo], **kw: object) -> MediaInfo:
    return MediaInfo(id="dQw4w9WgXcQ", title="T", formats=tuple(formats), **kw)  # type: ignore[arg-type]
