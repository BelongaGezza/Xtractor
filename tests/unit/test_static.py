"""Static gates over the source tree (plan section 4)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "xtractor"


def modules() -> list[Path]:
    return sorted(SRC.glob("*.py"))


def test_print_always_targets_a_stream() -> None:
    """Only the single success print (marked ``# stdout-ok``) may omit ``file=``."""
    offenders = []
    for path in modules():
        lines = path.read_text().splitlines()
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and not any(k.arg == "file" for k in node.keywords)
                and "stdout-ok" not in lines[node.lineno - 1]
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_yt_dlp_is_confined_to_ytdlp_module() -> None:
    for path in modules():
        if path.name == "ytdlp.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not [n for n in names if n.split(".")[0] in ("yt_dlp", "youtube_dl")], path.name


def test_no_shell_true_anywhere() -> None:
    for path in modules():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                raise AssertionError(f"shell= used in {path.name}")
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("system", "popen"):
                raise AssertionError(f"os.system/popen used in {path.name}")


def test_ffmpeg_lookup_is_isolated() -> None:
    for path in modules():
        if path.name != "ffmpeg.py":
            assert 'which("ffmpeg")' not in path.read_text(), path.name
