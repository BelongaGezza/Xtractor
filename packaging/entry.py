"""PyInstaller entry point for the single-file Xtractor binary."""

import sys

if sys.argv[1:] == ["--version"]:
    # Fast path: importing xtractor.cli loads ssl, subprocess, tarfile, ... and in a
    # --onefile build every extension module costs time at each launch. Output must
    # stay identical to the argparse action (tests/unit/test_entry.py enforces that).
    from xtractor.version import version_text

    sys.stdout.write(version_text() + "\n")
    sys.exit(0)

if sys.argv[1:] == ["--xtractor-selftest"]:
    import os

    if (
        os.environ.get("XTRACTOR_SELFTEST") == "1"
    ):  # release-workflow check, offline, inert otherwise
        from xtractor._selftest import run

        sys.exit(run())

from xtractor.cli import console_main

if __name__ == "__main__":
    console_main()
