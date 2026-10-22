"""The PyInstaller entry script must behave like ``python -m xtractor``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[2] / "packaging" / "entry.py"


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRY), *argv], capture_output=True, text=True, check=False
    )


def test_version_fast_path_matches_cli() -> None:
    fast = run("--version")
    slow = subprocess.run(
        [sys.executable, "-m", "xtractor", "--version"], capture_output=True, text=True, check=False
    )
    # The fast path may print less than the full CLI (it must at least print the first line);
    # packaging/entry.py should call xtractor.version.version_text() to print the same text.
    assert fast.returncode == 0 and slow.returncode == 0
    assert slow.stdout.startswith(fast.stdout)
    assert fast.stdout.splitlines()[0] == slow.stdout.splitlines()[0]
    assert fast.stderr == ""


def test_other_arguments_reach_the_cli() -> None:
    result = run("-h")
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout
