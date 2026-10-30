"""Compact native known-answer vectors, without emulator or firmware fixtures."""

import pytest

from iPodDB.ic_info.derivation import mix_byte, next_word


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        (0, 0x2405ECC0),
        (1, 0x42F36F91),
        (0xA90F, 0x789701BC),
        (0xA8D9, 0x1BC54873),
        (65535, 0x42F36F91),
    ],
)
def test_first_generator_word_matches_native(seed: int, expected: int) -> None:
    assert next_word(seed) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0, 255, 0),
        (1, 255, 255),
        (2, 2, 4),
        (0x57, 0x13, 0xFE),
        (0x80, 2, 0x1B),
        (255, 255, 19),
    ],
)
def test_canonical_byte_mix_matches_native(
    left: int, right: int, expected: int
) -> None:
    assert mix_byte(left, right) == expected


@pytest.mark.parametrize("value", [-1, 65536])
def test_generator_rejects_out_of_domain_seeds(value: int) -> None:
    with pytest.raises(ValueError, match="sixteen"):
        next_word(value)


@pytest.mark.parametrize(("left", "right"), [(-1, 0), (256, 0), (0, -1), (0, 256)])
def test_mix_rejects_out_of_domain_bytes(left: int, right: int) -> None:
    with pytest.raises(ValueError, match="one byte"):
        mix_byte(left, right)
