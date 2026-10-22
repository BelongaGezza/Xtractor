"""PyInstaller entry point for the single-file Xtractor binary."""

import sys

if sys.argv[1:] == ["--version"]:
    # Fast path: importing xtractor.cli loads ssl, subprocess, tarfile, ... and in a
    # --onefile build every extension module costs time at each launch. Output must
    # stay identical to the argparse action (tests/unit/test_entry.py enforces that).
    from xtractor import __version__

    sys.stdout.write(f"Xtractor {__version__}\n")
    sys.exit(0)

from xtractor.cli import console_main

if __name__ == "__main__":
    console_main()
