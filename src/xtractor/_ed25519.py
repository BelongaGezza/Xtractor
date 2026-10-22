"""Pure-Python Ed25519 (RFC 8032, section 5.1). Verification for ``--self-update``.

Imported lazily (only when an update is verified) so ``-h``/``--version`` start-up is not
affected. Signing helpers are included for the release scripts and the tests; they are
not used by the application at run time. This is deliberately small, not constant-time and
must never be used for anything but verifying public release signatures.
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)

Point = tuple[int, int, int, int]  # extended coordinates (X, Y, Z, T)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _add(a: Point, b: Point) -> Point:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p: Point) -> Point:
    r: Point = (0, 1, 1, 0)
    while s:
        if s & 1:
            r = _add(r, p)
        p = _add(p, p)
        s >>= 1
    return r


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0) or 0
_G: Point = (_GX, _GY, 1, _GX * _GY % _P)


def _encode(p: Point) -> bytes:
    zi = _inv(p[2])
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(s: bytes) -> Point | None:
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _eq(a: Point, b: Point) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _h(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key for a 32-byte secret seed."""
    a, _ = _expand(seed)
    return _encode(_mul(a, _G))


def sign(seed: bytes, message: bytes) -> bytes:
    """A 64-byte detached signature (release tooling and tests only)."""
    a, prefix = _expand(seed)
    pub = _encode(_mul(a, _G))
    r = _h(prefix + message) % _Q
    r_enc = _encode(_mul(r, _G))
    s = (r + _h(r_enc + pub + message) * a) % _Q
    return r_enc + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True only for a valid signature of ``message`` under ``public``. Never raises."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a_pt = _decode(public)
    r_pt = _decode(signature[:32])
    if a_pt is None or r_pt is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    k = _h(signature[:32] + public + message) % _Q
    return _eq(_mul(s, _G), _add(r_pt, _mul(k, a_pt)))
