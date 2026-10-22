#!/usr/bin/env bash
# Reproducible build of a minimal, static, LGPL ffmpeg (+ ffprobe for tests) for arm64 macOS.
#
# Pinned sources (sha256 verified): ffmpeg, LAME (libmp3lame), Opus. Output in build/:
#   build/ffmpeg  build/ffprobe  build/BUILDINFO-ffmpeg.json
# ffprobe is built only for verification (scripts/accept_binary.sh); it is NOT embedded,
# because Xtractor and yt-dlp only need ffmpeg itself.
# Prerequisites: Xcode command line tools, make, pkgconf (brew install pkgconf), xz.
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "$0")/common.sh"

FFMPEG_VERSION=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz"
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
LAME_URL="https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz"
OPUS_VERSION=1.6.1
OPUS_SHA256=6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1
OPUS_URL="https://downloads.xiph.org/releases/opus/opus-$OPUS_VERSION.tar.gz"

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || die "this build targets arm64 macOS only"
command -v pkg-config >/dev/null || command -v pkgconf >/dev/null || die "pkgconf is required (brew install pkgconf)"

JOBS="$(sysctl -n hw.ncpu)"
SRC="$BUILD_DIR/src"
WORK="$BUILD_DIR/ffwork"
PREFIX="$WORK/static"
mkdir -p "$SRC" "$BUILD_DIR"

fetch_verified "$FFMPEG_URL" "$SRC/ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"
fetch_verified "$LAME_URL" "$SRC/lame-$LAME_VERSION.tar.gz" "$LAME_SHA256"
fetch_verified "$OPUS_URL" "$SRC/opus-$OPUS_VERSION.tar.gz" "$OPUS_SHA256"

rm -rf "$WORK"; mkdir -p "$WORK" "$PREFIX"
tar -xf "$SRC/ffmpeg-$FFMPEG_VERSION.tar.xz" -C "$WORK"
tar -xf "$SRC/lame-$LAME_VERSION.tar.gz" -C "$WORK"
tar -xf "$SRC/opus-$OPUS_VERSION.tar.gz" -C "$WORK"

export MACOSX_DEPLOYMENT_TARGET=14.0
export CFLAGS="-O2 -arch arm64"
export LDFLAGS="-arch arm64"

log "building LAME $LAME_VERSION (static, encoder only)"
( cd "$WORK/lame-$LAME_VERSION" \
  && ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-frontend \
       --disable-decoder --disable-dependency-tracking >"$WORK/lame.log" 2>&1 \
  && make -j"$JOBS" >>"$WORK/lame.log" 2>&1 && make install >>"$WORK/lame.log" 2>&1 )

log "building Opus $OPUS_VERSION (static)"
( cd "$WORK/opus-$OPUS_VERSION" \
  && ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-doc \
       --disable-extra-programs --disable-dependency-tracking >"$WORK/opus.log" 2>&1 \
  && make -j"$JOBS" >>"$WORK/opus.log" 2>&1 && make install >>"$WORK/opus.log" 2>&1 )

log "configuring ffmpeg $FFMPEG_VERSION"
# Keep this list in sync with docs/BUILD_NOTES.md and THIRD_PARTY_NOTICES (LGPL source offer).
CONFIGURE_FLAGS=(
  --prefix=/usr/local  # never installed; fixed so the recorded configure line carries no build path
  --cc=clang --arch=arm64 --target-os=darwin
  --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-network
  --disable-ffplay --enable-ffmpeg --enable-ffprobe --disable-shared --enable-static
  --enable-libmp3lame --enable-libopus --enable-zlib
  "--extra-cflags=-I$PREFIX/include" "--extra-ldflags=-L$PREFIX/lib -Wl,-dead_strip"
  --enable-protocol=file,pipe,fd
  --enable-demuxer=mov,mpegts,matroska,ogg,mp3,flac,wav,aac,image2,image2pipe,image_jpeg_pipe,image_png_pipe,image_webp_pipe,concat,ffmetadata,opus
  --enable-muxer=matroska_audio,mp4,ipod,mov,matroska,webm,ogg,opus,mp3,flac,wav,adts,null,image2,mjpeg,ffmetadata,mpegts
  --enable-decoder=aac,aac_fixed,mp3,mp3float,opus,libopus,vorbis,flac,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8,webp,png,mjpeg
  --enable-encoder=aac,libmp3lame,libopus,flac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,mjpeg,png
  --enable-parser=aac,aac_latm,opus,vorbis,flac,mpegaudio,h264,hevc,vp9,av1,mjpeg,png,webp,vp8
  --enable-bsf=aac_adtstoasc,extract_extradata,h264_mp4toannexb,hevc_mp4toannexb,vp9_superframe,vp9_superframe_split,null,opus_metadata
  --enable-filter=aresample,anull,null,aformat,format,scale,atrim,trim,volume,loudnorm,afade,atempo,pan,amix,anullsrc,anullsink,nullsink,setpts,asetpts,crop,pad,amerge,channelmap
)
mkdir -p "$WORK/ffobj"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
# Only static archives exist in $PREFIX, so the linker cannot pick a dylib.
( cd "$WORK/ffobj" \
  && "../ffmpeg-$FFMPEG_VERSION/configure" "${CONFIGURE_FLAGS[@]}" \
       >"$WORK/ffconfigure.log" 2>&1 ) || { tail -30 "$WORK/ffconfigure.log" >&2; die "ffmpeg configure failed"; }
grep -q "^License: LGPL" "$WORK/ffconfigure.log" || die "configure did not report an LGPL licence"

log "building ffmpeg"
( cd "$WORK/ffobj" && make -j"$JOBS" >"$WORK/ffmake.log" 2>&1 ) || { tail -30 "$WORK/ffmake.log" >&2; die "ffmpeg make failed"; }
cp "$WORK/ffobj/ffmpeg" "$WORK/ffobj/ffprobe" "$BUILD_DIR/"
strip -x "$BUILD_DIR/ffmpeg" "$BUILD_DIR/ffprobe"
codesign --force -s - "$BUILD_DIR/ffmpeg" "$BUILD_DIR/ffprobe"

# Compliance gates (R15): LGPL, no GPL/nonfree, no third-party dylibs.
LICENSE_TXT="$("$BUILD_DIR/ffmpeg" -hide_banner -L | head -3)"
case "$("$BUILD_DIR/ffmpeg" -hide_banner -version)" in
  *--enable-gpl*|*--enable-nonfree*|*--enable-version3*) die "GPL/nonfree flag present in ffmpeg build" ;;
esac
if otool -L "$BUILD_DIR/ffmpeg" | tail -n +2 | grep -v -E '/usr/lib/|/System/Library/' ; then
  die "ffmpeg links a non-system dynamic library"
fi

log "writing BUILDINFO-ffmpeg.json"
FLAGS_JSON="$(printf '%s\n' "${CONFIGURE_FLAGS[@]}" | python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin]))')"
python3 - "$BUILD_DIR/BUILDINFO-ffmpeg.json" "$FLAGS_JSON" <<PY
import json, sys
out, flags = sys.argv[1], json.loads(sys.argv[2])
info = {
    "ffmpeg": {"version": "$FFMPEG_VERSION", "source_sha256": "$FFMPEG_SHA256", "url": "$FFMPEG_URL"},
    "lame": {"version": "$LAME_VERSION", "source_sha256": "$LAME_SHA256", "url": "$LAME_URL"},
    "opus": {"version": "$OPUS_VERSION", "source_sha256": "$OPUS_SHA256", "url": "$OPUS_URL"},
    "configure_flags": flags,
    "license": """$LICENSE_TXT""",
    "sha256": {"ffmpeg": "$(sha256_of "$BUILD_DIR/ffmpeg")", "ffprobe": "$(sha256_of "$BUILD_DIR/ffprobe")"},
    "size_bytes": {"ffmpeg": $(stat -f %z "$BUILD_DIR/ffmpeg"), "ffprobe": $(stat -f %z "$BUILD_DIR/ffprobe")},
}
json.dump(info, open(out, "w"), indent=2)
PY
log "done: $(ls -l "$BUILD_DIR/ffmpeg" | awk '{print $5}') bytes ffmpeg"
