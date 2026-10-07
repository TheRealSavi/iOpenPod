"""Lossless fingerprint cache migration and bounded malformed-input handling."""

import base64
import random
import struct
import zlib

import pytest

from iOpenPod.app.media.fingerprint_codec import decode_fingerprint, encode_fingerprint


def test_long_fingerprint_is_compact_and_preserves_every_unsigned_value() -> None:
    random_source = random.Random(732)
    values = [0, 2**32 - 1, *(random_source.getrandbits(32) for _ in range(948))]
    raw = ",".join(str(value) for value in values)
    encoded = encode_fingerprint(raw)
    assert encoded.startswith("u32z:")
    assert len(encoded) < len(raw) * 0.6
    assert decode_fingerprint(encoded) == raw


@pytest.mark.parametrize("value", ["", "0", "1,2,3", "4294967295,0"])
def test_short_and_empty_fingerprints_round_trip(value: str) -> None:
    assert decode_fingerprint(encode_fingerprint(value)) == value
    assert decode_fingerprint(value) == value


def test_legacy_decimal_fingerprints_are_normalized() -> None:
    assert decode_fingerprint("0001,002,0") == "1,2,0"


def _packed(payload: bytes) -> str:
    return "u32z:" + base64.b64encode(payload).decode("ascii")


@pytest.mark.parametrize(
    "value",
    [
        "1,-1",
        "4294967296",
        "1,,2",
        "\u0661,2",
        "1,2,",
        "future:abc",
        "u32z:not-base64!",
        "u32z:",
        "u32z:é",
        _packed(zlib.compress(b"")),
        _packed(zlib.compress(b"123")),
        _packed(zlib.compress(struct.pack("<I", 1))[:-1]),
        _packed(zlib.compress(struct.pack("<I", 1)) + b"trailing"),
        _packed(zlib.compress(struct.pack("<I", 1)) * 2),
    ],
)
def test_corrupt_fingerprints_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        decode_fingerprint(value)


def test_compressed_expansion_is_bounded() -> None:
    oversized = _packed(zlib.compress(b"\0" * (4 * 250_000 + 4)))
    with pytest.raises(ValueError, match="oversized"):
        decode_fingerprint(oversized)


def test_packed_input_is_bounded_before_decoding() -> None:
    with pytest.raises(ValueError, match="input limit"):
        decode_fingerprint("u32z:" + "A" * 1_400_000)


def test_fingerprint_value_count_is_bounded() -> None:
    with pytest.raises(ValueError):
        encode_fingerprint(",".join("0" for _ in range(250_001)))
