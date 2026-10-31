"""Authenticate, decode and encode the supported IC-Info protected envelopes."""

import hashlib
import hmac

from .cipher import TableCipher
from .envelope_tables import AUTH, BODY

MAX_ENVELOPE_BYTES = 0x80000
_VERSIONS = frozenset((0x00060002, 0x00060003))
_BODY_ENCODE = bytes((value * 181) & 255 for value in range(256))
_BODY_DECODE = bytes((value * 157) & 255 for value in range(256))
# Fixed native IV after its byte-representation conversion; not a per-file nonce.
_IV = bytes.fromhex("16b8c8430cce4ee8d44872fd98bdd737")


def _identity_material(guid: bytes) -> tuple[bytes, bytes]:
    if len(guid) != 8:
        raise ValueError("A FireWire GUID must contain exactly eight bytes")
    indices = tuple((index << 8) | guid[index % 8] for index in range(16))
    return (
        bytes(
            (205 * ((34835 * value + 142695406) % 65014) + 205) & 255
            for value in indices
        ),
        bytes(
            (185 * ((15280 * value + 125213766) % 63140) + 210) & 255
            for value in indices
        ),
    )


def _length(backing: bytes) -> int:
    if len(backing) < 32 or backing[:12] != bytes(12) or backing[16:20] != b"sean":
        raise ValueError("The decoded authorization store has an invalid root")
    length = int.from_bytes(backing[12:16], "big") + 12
    if length < 32 or length > len(backing):
        raise ValueError("The decoded authorization store has an invalid length")
    return length


def decode_envelope(blob: bytes, guid: bytes) -> tuple[int, bytes]:
    """Verify device binding before returning the version and clear record tree."""
    auth_key, body_key = _identity_material(guid)
    if not 52 <= len(blob) <= MAX_ENVELOPE_BYTES or (len(blob) - 20) % 16:
        raise ValueError("Invalid IC-Info envelope size")
    version = int.from_bytes(blob[:4], "big")
    if version not in _VERSIONS:
        raise ValueError("Unsupported IC-Info envelope version")
    expected = TableCipher(AUTH, auth_key).encrypt(hashlib.md5(blob[:-16]).digest())
    if not hmac.compare_digest(expected, blob[-16:]):
        raise ValueError("IC-Info authentication failed for the supplied device GUID")
    cipher = TableCipher(BODY, body_key)
    chain = _IV
    result = bytearray()
    for offset in range(4, len(blob) - 16, 16):
        encrypted = cipher.decode_output(blob[offset : offset + 16])
        plain = cipher.decrypt_internal(encrypted)
        result.extend(
            cipher.decode_input(
                bytes(a ^ b for a, b in zip(plain, chain, strict=True))
            ).translate(_BODY_DECODE)
        )
        chain = encrypted
    backing = bytes(result)
    length = _length(backing)
    if len(backing) - length >= 16 or any(backing[length:]):
        raise ValueError("Invalid IC-Info envelope padding")
    return version, backing[:length]


def encode_envelope(backing: bytes, guid: bytes, version: int = 0x00060002) -> bytes:
    """Encode an entire record tree; the caller owns persistence and merging."""
    auth_key, body_key = _identity_material(guid)
    if version not in _VERSIONS:
        raise ValueError("Unsupported IC-Info envelope version")
    if _length(backing) != len(backing):
        raise ValueError("The authorization tree has trailing bytes")
    padded_length = (len(backing) + 15) & ~15
    if padded_length + 20 > MAX_ENVELOPE_BYTES:
        raise ValueError("IC-Info envelope exceeds its size limit")
    padded = backing.ljust(padded_length, b"\0").translate(_BODY_ENCODE)
    cipher = TableCipher(BODY, body_key)
    result = bytearray(version.to_bytes(4, "big"))
    chain = _IV
    for offset in range(0, len(padded), 16):
        plain = cipher.encode_input(padded[offset : offset + 16])
        chain = cipher.encrypt_internal(
            bytes(a ^ b for a, b in zip(plain, chain, strict=True))
        )
        result.extend(cipher.encode_output(chain))
    result.extend(TableCipher(AUTH, auth_key).encrypt(hashlib.md5(result).digest()))
    return bytes(result)
