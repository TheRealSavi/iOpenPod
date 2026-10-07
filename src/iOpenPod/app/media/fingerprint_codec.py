"""Compact lossless cache encoding for raw algorithm-2 Acoustic Fingerprints.

Runtime matching keeps the canonical unsigned comma-separated sequence. Cache
versions that support this codec may store it as compressed little-endian uint32
values instead. The prefix is independent of the surrounding catalog version.
"""

from __future__ import annotations

import base64
import binascii
import struct
import zlib

from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    normalize_fpcalc_fingerprint,
)

_PREFIX = "u32z:"
_MAX_VALUES = 250_000
_MAX_BINARY_BYTES = 4 * _MAX_VALUES
_MAX_ENCODED_CHARS = 4 * ((_MAX_BINARY_BYTES + 1024 + 2) // 3)


def encode_fingerprint(value: str) -> str:
    """Return a bounded, canonical raw or packed fingerprint, whichever is smaller."""

    if not value:
        return ""
    canonical = _canonical(value)
    numbers = tuple(int(part) for part in canonical.split(","))
    packed = struct.pack(f"<{len(numbers)}I", *numbers)
    encoded = _PREFIX + base64.b64encode(zlib.compress(packed, level=1)).decode("ascii")
    return encoded if len(encoded) < len(canonical) else canonical


def decode_fingerprint(value: str) -> str:
    """Read legacy raw values or one complete bounded packed stream.

    Both compressed input and decompressed output are bounded. Truncated streams,
    trailing bytes, concatenated streams and partial uint32 values are rejected.
    Catalog readers additionally bound the combined decoded size of all records.
    """

    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return _canonical(value)
    encoded = value[len(_PREFIX) :]
    if len(encoded) > _MAX_ENCODED_CHARS:
        raise ValueError("Packed Acoustic Fingerprint exceeds its input limit")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        decompressor = zlib.decompressobj()
        packed = decompressor.decompress(compressed, _MAX_BINARY_BYTES + 1)
    except (ValueError, binascii.Error, zlib.error) as error:
        raise ValueError("Invalid packed Acoustic Fingerprint") from error
    if (
        not packed
        or len(packed) > _MAX_BINARY_BYTES
        or len(packed) % 4
        or not decompressor.eof
        or decompressor.unconsumed_tail
        or decompressor.unused_data
    ):
        raise ValueError("Invalid or oversized packed Acoustic Fingerprint")
    return ",".join(str(number[0]) for number in struct.iter_unpack("<I", packed))


def _canonical(value: str) -> str:
    if len(value) > 11 * _MAX_VALUES:
        raise ValueError("Raw Acoustic Fingerprint exceeds its input limit")
    try:
        return normalize_fpcalc_fingerprint(value)
    except FpcalcError as error:
        raise ValueError("Invalid raw Acoustic Fingerprint") from error
