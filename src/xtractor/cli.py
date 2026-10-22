"""Command-line interface: parser, option parsing and the top-level error handler."""

from __future__ import annotations

import argparse
import functools
import sys
import textwrap
import traceback
from collections.abc import Sequence
from typing import NoReturn

from . import __version__
from .errors import (
    EXIT_CODE_TABLE,
    EXIT_INTERNAL,
    EXIT_INTERRUPTED,
    EXIT_OK,
    InternalError,
    UsageError,
    XtractorError,
    classify_exception,
)
from .ffmpeg import ensure_dependencies
from .options import (
    AUDIO_FORMATS,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_BITRATE,
    DEFAULT_RESOLUTION,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_TEMPLATE,
    DEFAULT_VIDEO_FORMAT,
    RESOLUTIONS,
    SAMPLE_RATES,
    VIDEO_FORMATS,
    Options,
    build_options,
)

PROG = "Xtractor"

LEGAL_NOTICE = (
    "Legal notice: YouTube's Terms of Service restrict downloading content without "
    "permission. Use Xtractor only for content you have the right to download (your own "
    "uploads, Creative Commons or public-domain material, content with the owner's "
    "permission, or lawful personal archival). Xtractor does not and will not circumvent "
    "DRM; DRM-protected streams are refused."
)

EXAMPLES = """\
Examples:
  Xtractor -a https://youtu.be/VIDEOID
  Xtractor -a --sample-rate 48000 --audio-format wav https://youtu.be/VIDEOID
  Xtractor -v --resolution 720 -o ~/Movies https://youtu.be/VIDEOID
  Xtractor -a -q -o out/ https://youtu.be/VIDEOID
"""


def _exit_code_text() -> str:
    lines = ["Exit codes:"]
    lines += [f"  {code:<4} {meaning}" for code, meaning in EXIT_CODE_TABLE]
    return "\n".join(lines)


def epilog() -> str:
    return f"{EXAMPLES}\n{_exit_code_text()}\n\n{textwrap.fill(LEGAL_NOTICE, 98)}"


class _SpecFormatter(argparse.RawDescriptionHelpFormatter):
    """Render ``-o, --output PATH`` (flags first, metavar once) as in the specification."""

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings or action.nargs == 0:
            return super()._format_action_invocation(action)
        metavar = self._format_args(action, self._get_default_metavar_for_optional(action))
        return ", ".join(action.option_strings) + " " + metavar


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser; help output follows the grouped layout of the specification."""
    formatter = functools.partial(_SpecFormatter, max_help_position=30, width=100)
    p = _Parser(
        prog=PROG,
        usage=f"{PROG} [OPTIONS] URL",
        description="Extract the audio or video track from a YouTube video.",
        epilog=epilog(),
        formatter_class=formatter,
        add_help=False,
        allow_abbrev=False,
    )
    p.add_argument("url", nargs="?", help=argparse.SUPPRESS, metavar="URL")

    mode = p.add_argument_group("Mode (exactly one required)")
    mode.add_argument("-a", "--audio", action="store_true", help="Extract audio only")
    mode.add_argument("-v", "--video", action="store_true", help="Download video (with audio)")

    rates = "|".join(map(str, SAMPLE_RATES))
    audio = p.add_argument_group("Audio options (with -a)")
    audio.add_argument(
        "--sample-rate",
        metavar="HZ",
        help=f"{rates}  [default: {DEFAULT_SAMPLE_RATE}; opus: 48000]",
    )
    audio.add_argument(
        "--audio-format",
        metavar="FMT",
        help=f"{'|'.join(AUDIO_FORMATS)}  [default: {DEFAULT_AUDIO_FORMAT}]",
    )
    audio.add_argument(
        "--audio-quality",
        metavar="BR",
        help=(
            "Bitrate for lossy formats, e.g. 192k  "
            f"[default: {DEFAULT_BITRATE} when transcoding; m4a is copied if untouched]"
        ),
    )

    video = p.add_argument_group("Video options (with -v)")
    video.add_argument(
        "--resolution",
        metavar="RES",
        help=f"{'|'.join(RESOLUTIONS)}  [default: {DEFAULT_RESOLUTION}]",
    )
    video.add_argument(
        "--video-format",
        metavar="FMT",
        help=f"{'|'.join(VIDEO_FORMATS)}  [default: {DEFAULT_VIDEO_FORMAT}]",
    )
    video.add_argument(
        "--strict-format",
        action="store_true",
        help="Fail instead of switching container/codec",
    )

    gen = p.add_argument_group("General")
    gen.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Output directory, or full file path  [default: current dir]",
    )
    gen.add_argument(
        "-n",
        "--name",
        metavar="TEMPLATE",
        help=(
            f'Filename template  [default: "{DEFAULT_TEMPLATE.replace("%", "%%")}"]; '
            "fields: title, id, uploader, upload_date, resolution"
        ),
    )
    gen.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing file (default: skip and exit 0 with notice)",
    )
    gen.add_argument("-q", "--quiet", action="store_true", help="Errors only")
    gen.add_argument(
        "--verbose",
        action="store_true",
        help="Debug detail including underlying tool commands",
    )
    gen.add_argument(
        "--list-formats",
        action="store_true",
        help="Show available streams for URL and exit",
    )
    gen.add_argument(
        "--no-playlist",
        action="store_true",
        help="Treat URL with list= parameter as the single video (default behaviour)",
    )
    gen.add_argument(
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
        help="Print version and exit",
    )
    gen.add_argument("-h", "--help", action="help", help="Show this help and exit")
    return p


def parse_args(argv: Sequence[str] | None = None) -> Options:
    """Parse and validate ``argv``. Raises :class:`UsageError`; -h/--version raise SystemExit."""
    ns = build_parser().parse_args(list(argv) if argv is not None else None)
    return build_options(ns)


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run Xtractor and return the process exit code."""
    verbose = False
    try:
        try:
            opts = parse_args(argv)
        except SystemExit as exc:  # -h / --version
            code = exc.code
            return code if isinstance(code, int) else EXIT_OK
        verbose = opts.verbose

        if not opts.quiet:
            for warning in opts.warnings:
                print(f"{PROG}: warning: {warning}", file=sys.stderr)

        if not opts.list_formats:
            ensure_dependencies()

        raise InternalError("downloading is not implemented yet")
    except KeyboardInterrupt:
        print(f"\n{PROG}: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:
        err: XtractorError = classify_exception(exc)
        _error(str(err))
        if isinstance(err, UsageError):
            print(f"Try '{PROG} -h' for help.", file=sys.stderr)
        if verbose:
            traceback.print_exception(exc, file=sys.stderr)
        return err.exit_code if err.exit_code else EXIT_INTERNAL


def console_main() -> None:
    """Console-script entry point."""
    sys.exit(main())
