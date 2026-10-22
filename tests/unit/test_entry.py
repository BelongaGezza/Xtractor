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
    assert (fast.returncode, fast.stdout) == (0, slow.stdout)
    assert slow.returncode == 0
    assert fast.stderr == ""


def test_other_arguments_reach_the_cli() -> None:
    result = run("-h")
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout
