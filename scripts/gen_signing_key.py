#!/usr/bin/env python3
"""Generate the Ed25519 release-signing key pair.

The PRIVATE seed (base64) is written to ~/.config/xtractor-signing/ed25519.key with mode
0600 and is never printed or placed in the repository. Only the PUBLIC key (hex) is printed;
embed it in ``TRUSTED_PUBLIC_KEYS`` in src/xtractor/selfupdate.py. Refuses to overwrite.

    scripts/gen_signing_key.py [--dir DIR]

Then, once and by hand, store the secret in GitHub (environment "release"):
    gh secret set XTRACTOR_SIGNING_KEY --env release < ~/.config/xtractor-signing/ed25519.key
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from xtractor import _ed25519


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, default=Path.home() / ".config" / "xtractor-signing")
    ns = ap.parse_args(argv)
    ns.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ns.dir, 0o700)
    path = ns.dir / "ed25519.key"
    seed = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"error: {path} already exists; not overwriting", file=sys.stderr)
        return 1
    with os.fdopen(fd, "w") as fh:
        fh.write(base64.b64encode(seed).decode() + "\n")
    print(f"private key written to {path} (mode 0600); back it up offline", file=sys.stderr)
    print(_ed25519.public_key(seed).hex())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
