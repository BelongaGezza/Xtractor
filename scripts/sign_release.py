#!/usr/bin/env python3
"""Sign dist/SHA256SUMS: write the detached signature SHA256SUMS.sig (base64).

    XTRACTOR_SIGNING_KEY=<base64 seed> scripts/sign_release.py [SHA256SUMS [OUT]]

The signed message is the domain-separation prefix from ``xtractor.selfupdate`` plus the
exact bytes of SHA256SUMS, so a signature cannot be replayed for another purpose. The key
is read only from the environment and is never printed. The signature is verified against
the embedded public keys before it is written.
"""

from __future__ import annotations

import base64
import binascii
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from xtractor import _ed25519, selfupdate


def main(argv: list[str]) -> int:
    raw = os.environ.get("XTRACTOR_SIGNING_KEY", "").strip()
    if not raw:
        print("error: XTRACTOR_SIGNING_KEY is not set", file=sys.stderr)
        return 1
    try:
        seed = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        print("error: XTRACTOR_SIGNING_KEY is not valid base64", file=sys.stderr)
        return 1
    if len(seed) != 32:
        print("error: XTRACTOR_SIGNING_KEY must decode to 32 bytes", file=sys.stderr)
        return 1
    sums = Path(argv[0] if argv else "dist/SHA256SUMS")
    out = Path(argv[1]) if len(argv) > 1 else sums.with_name(sums.name + ".sig")
    data = sums.read_bytes()
    sig = _ed25519.sign(seed, selfupdate.SIGNED_PREFIX + data)
    if not selfupdate.verify_signature(data, base64.b64encode(sig)):
        print(
            "error: the signing key does not match any key embedded in selfupdate.py",
            file=sys.stderr,
        )
        return 1
    out.write_bytes(base64.b64encode(sig) + b"\n")
    print(f"signed {sums} -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
