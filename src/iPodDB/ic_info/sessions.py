"""IC-Info account sessions, using the four evidenced firmware RSA key groups.

The small factors are compatibility constants recovered from the respective
firmware's CRT preparation routines. They are not user account credentials.
No executable firmware or emulator is used by this module.
"""

import json
from functools import lru_cache
from importlib.resources import files
from math import lcm
from typing import cast

from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA

_GROUPS = {
    13: "video",
    20: "video",
    25: "video",
    24: "classic",
    33: "classic",
    35: "classic",
    38: "classic",
    26: "nano34",
    31: "nano34",
    34: "nano5",
}


@lru_cache(maxsize=4)
def _key(group: str) -> RSA.RsaKey:
    # Loading packaged format constants is not device/Host persistence.
    raw: object = json.loads(
        files(__package__).joinpath("session_factors.json").read_text()
    )
    if not isinstance(raw, dict):
        raise ValueError("Invalid IC-Info session constants")
    entries = cast("dict[str, object]", raw)
    row = entries.get(group)
    if not isinstance(row, dict):
        raise ValueError("Missing IC-Info session constants")
    factors = cast("dict[str, object]", row)
    p_hex = factors.get("p")
    q_hex = factors.get("q")
    if not isinstance(p_hex, str) or not isinstance(q_hex, str):
        raise ValueError("Invalid IC-Info RSA factors")
    p, q = int(p_hex, 16), int(q_hex, 16)
    return RSA.construct((p * q, 65537, pow(65537, -1, lcm(p - 1, q - 1)), p, q))


def _family_key(family: int) -> RSA.RsaKey:
    try:
        group = _GROUPS[family]
    except KeyError:
        raise ValueError(f"Unsupported IC-Info updater family: {family}") from None
    return _key(group)


def decode_session(ciphertext: bytes, family: int) -> bytes:
    """Validate RSA-OAEP-SHA1 and return exactly one 16-byte account session."""
    if len(ciphertext) != 128:
        raise ValueError("IC-Info account session must contain 128 encrypted bytes")
    plain = PKCS1_OAEP.new(_family_key(family), hashAlgo=SHA1, label=b"").decrypt(
        ciphertext
    )
    if len(plain) != 16:
        raise ValueError("IC-Info decoded account session must contain 16 bytes")
    return plain


def encode_session(session: bytes, family: int) -> bytes:
    """Wrap a session for a firmware group using independently random OAEP padding."""
    if len(session) != 16:
        raise ValueError("IC-Info account session must contain 16 bytes")
    return PKCS1_OAEP.new(
        _family_key(family).public_key(), hashAlgo=SHA1, label=b""
    ).encrypt(session)
