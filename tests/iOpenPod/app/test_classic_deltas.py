"""Exercise native artwork packet boundaries and byte-exact reconstruction."""

import random

import pytest
from scripts.firmware.classic_deltas import encode_xor_delta


def decode(packets: bytes) -> bytes:
    """Independent packet reader; the ARM probe tests the production C decoder."""
    result = bytearray()
    cursor = 0
    while cursor < len(packets):
        control = packets[cursor]
        cursor += 1
        if control < 128:
            count = control + 1
            assert cursor + count <= len(packets)
            result.extend(packets[cursor : cursor + count])
            cursor += count
        else:
            width = 1 if control < 192 else 2
            count = (control & 63) + (3 if width == 1 else 2)
            assert cursor + width <= len(packets)
            result.extend(packets[cursor : cursor + width] * count)
            cursor += width
    return bytes(result)


@pytest.mark.parametrize(
    "length", [0, 1, 2, 3, 4, 65, 66, 67, 127, 128, 129, 130, 131, 513]
)
def test_xor_packets_reconstruct_all_boundary_patterns(length: int) -> None:
    randomizer = random.Random(length)
    original = randomizer.randbytes(length)
    for changed in (
        original,
        bytes(length),
        b"\x78" * length,
        (b"\x24\x92" * length)[:length],
        bytes(i % 256 for i in range(length)),
        randomizer.randbytes(length),
    ):
        delta = decode(encode_xor_delta(original, changed))
        assert len(delta) == length
        assert bytes(a ^ b for a, b in zip(original, delta, strict=True)) == changed
        assert bytes(a ^ b for a, b in zip(changed, delta, strict=True)) == original
    # Zero originals directly exercise repeated-byte and repeated-word runs.
    for changed in (b"\x78" * length, (b"\x24\x92" * length)[:length]):
        assert decode(encode_xor_delta(bytes(length), changed)) == changed


def test_packet_runs_can_start_at_odd_addresses() -> None:
    changed = b"x" + b"ab" * 140 + b"z" * 70 + bytes(range(256)) + b"ab" * 2
    assert decode(encode_xor_delta(bytes(len(changed)), changed)) == changed


def test_mismatched_delta_lengths_are_rejected() -> None:
    with pytest.raises(ValueError):
        encode_xor_delta(b"a", b"ab")
