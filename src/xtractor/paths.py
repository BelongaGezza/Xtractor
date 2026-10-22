"""Filename sanitising, output resolution, temp dirs and atomic moves."""

from __future__ import annotations

import os
import re
import shutil
import signal
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from .errors import UsageError

MAX_NAME_BYTES = 200
TEMPLATE_FIELDS = ("title", "id", "uploader", "upload_date", "resolution")
TEMP_PREFIX = ".Xtractor-"

_FORBIDDEN_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WS_RE = re.compile(r"\s+")
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_FIELD_RE = re.compile(r"%\((\w+)\)s|%%|%")


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """Cut ``text`` to ``max_bytes`` of UTF-8 without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def sanitise(name: str, *, ext: str = "", fallback: str = "video") -> str:
    """Return a file *stem* that is safe on macOS, Linux and Windows.

    ``ext`` (without dot) is only used to reserve room in the byte-length cap; it is
    not appended. An empty result becomes ``fallback``.
    """
    stem = unicodedata.normalize("NFC", name)
    stem = _FORBIDDEN_RE.sub(" ", stem)
    stem = _WS_RE.sub(" ", stem).strip()
    stem = stem.strip(" .")
    reserve = len(ext.encode("utf-8")) + 1 if ext else 0
    stem = _truncate_bytes(stem, MAX_NAME_BYTES - reserve).strip(" .")
    if not stem:
        stem = fallback
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    return stem


def validate_template(template: str) -> None:
    """Raise :class:`UsageError` if the template has unknown fields or stray ``%``."""
    if not template:
        raise UsageError("--name template must not be empty")
    for m in _FIELD_RE.finditer(template):
        if m.group(0) == "%":
            raise UsageError(
                f"invalid --name template {template!r}: use %(field)s, or %% for a literal %"
            )
        if m.group(1) is not None and m.group(1) not in TEMPLATE_FIELDS:
            raise UsageError(
                f"unknown field %({m.group(1)})s in --name template; "
                f"valid fields: {', '.join(TEMPLATE_FIELDS)}"
            )


def expand_template(template: str, fields: Mapping[str, str | None]) -> str:
    """Expand a validated template. Missing/empty field values become ``NA``."""
    validate_template(template)

    def repl(m: re.Match[str]) -> str:
        if m.group(0) == "%%":
            return "%"
        value = fields.get(m.group(1) or "")
        return value if value else "NA"

    return _FIELD_RE.sub(repl, template)


def looks_like_file(output: str) -> bool:
    """S6: a path is a directory if it exists as one, ends in a separator, or has no suffix."""
    if output.endswith(("/", os.sep)):
        return False
    path = Path(output).expanduser()
    if path.is_dir():
        return False
    return path.suffix != ""


def resolve_output(
    output: str | None,
    *,
    output_is_file: bool,
    template: str,
    fields: Mapping[str, str | None],
    ext: str,
    cwd: Path | None = None,
) -> Path:
    """Compute the final output path (does not touch the filesystem).

    ``ext`` is the extension (no dot) dictated by the chosen format. A user-supplied
    file path whose extension differs raises :class:`UsageError`.
    """
    base = cwd if cwd is not None else Path.cwd()
    if output_is_file:
        assert output is not None
        path = Path(output).expanduser()
        path = path if path.is_absolute() else base / path
        if path.suffix.lower() != f".{ext}":
            raise UsageError(
                f"output file extension {path.suffix!r} does not match the resulting "
                f"format; expected '.{ext}'"
            )
        return path
    directory = Path(output).expanduser() if output else base
    directory = directory if directory.is_absolute() else base / directory
    stem = sanitise(
        expand_template(template, fields),
        ext=ext,
        fallback=(fields.get("id") or "video"),
    )
    return directory / f"{stem}.{ext}"


def should_skip(path: Path, *, overwrite: bool) -> bool:
    """S5: an existing target is skipped unless ``--overwrite`` was given."""
    return path.exists() and not overwrite


@contextmanager
def temp_workdir(parent: Path) -> Iterator[Path]:
    """Create ``parent/.Xtractor-<rand>/`` (same filesystem as the target) and always remove it."""
    parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=parent))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def atomic_move(src: Path, dst: Path) -> None:
    """Atomically move ``src`` onto ``dst`` (same filesystem; replaces an existing file)."""
    os.replace(src, dst)


@contextmanager
def sigterm_as_interrupt() -> Iterator[None]:
    """Turn SIGTERM into ``KeyboardInterrupt`` so ``finally`` cleanup runs (exit 130)."""

    def handler(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    try:
        previous = signal.signal(signal.SIGTERM, handler)
    except ValueError:  # not in the main thread
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
