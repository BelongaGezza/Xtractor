from __future__ import annotations

import pytest

from xtractor import _ed25519 as ed

# RFC 8032 section 7.1 test vectors: (secret, public, message, signature)
VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e3970"
        "1cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613"
        "d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]


@pytest.mark.parametrize(("secret", "public", "message", "signature"), VECTORS)
def test_rfc8032_vectors(secret: str, public: str, message: str, signature: str) -> None:
    seed, pub, msg, sig = (bytes.fromhex(x) for x in (secret, public, message, signature))
    assert ed.public_key(seed) == pub
    assert ed.sign(seed, msg) == sig
    assert ed.verify(pub, msg, sig)


def test_rejects_tampering_and_garbage() -> None:
    seed = bytes(range(32))
    pub = ed.public_key(seed)
    sig = ed.sign(seed, b"hello")
    assert ed.verify(pub, b"hello", sig)
    assert not ed.verify(pub, b"hellp", sig)
    assert not ed.verify(pub, b"hello", sig[:-1] + bytes([sig[-1] ^ 1]))
    assert not ed.verify(pub, b"hello", bytes([sig[0] ^ 1]) + sig[1:])
    assert not ed.verify(ed.public_key(bytes(32)), b"hello", sig)
    assert not ed.verify(pub, b"hello", sig[:63])
    assert not ed.verify(pub[:31], b"hello", sig)
    # s >= group order is malleable and must be rejected
    big_s = (int.from_bytes(sig[32:], "little") + ed._Q).to_bytes(32, "little")
    assert not ed.verify(pub, b"hello", sig[:32] + big_s)
    assert not ed.verify(b"\xff" * 32, b"hello", sig)  # not a curve point
