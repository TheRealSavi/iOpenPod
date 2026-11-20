"""Native patch plans fail closed before an image can be published."""

import struct

import pytest
from scripts.firmware.classic_patches import (
    NativePatch,
    apply_patches,
    arm_call,
    arm_immediate,
    runtime_offset,
)
from scripts.firmware.classic_target import (
    DRAM_BASE,
    DRAM_END,
    DRAM_FILE,
    HEADER_BYTES,
    IRAM_BASE,
    IRAM_END,
)


def test_adjacent_patches_keep_extent_and_provenance() -> None:
    original = bytes(HEADER_BYTES) + b"abcdefgh"
    patched, records = apply_patches(
        original,
        (
            NativePatch(IRAM_BASE, b"abcd", b"ABCD", "first"),
            NativePatch(IRAM_BASE + 4, b"efgh", b"EFGH", "second"),
        ),
    )
    assert patched == bytes(HEADER_BYTES) + b"ABCDEFGH"
    assert original[-8:] == b"abcdefgh"
    assert [record.file_offset for record in records] == [
        HEADER_BYTES,
        HEADER_BYTES + 4,
    ]
    assert bytes.fromhex(records[0].before) == b"abcd"
    assert bytes.fromhex(records[1].after) == b"EFGH"
    assert [record.purpose for record in records] == ["first", "second"]


@pytest.mark.parametrize("second_before", [b"abcd", b"ABCD"])
def test_repeated_patch_rejected_even_if_preimage_matches(second_before: bytes) -> None:
    with pytest.raises(ValueError, match="Overlapping"):
        apply_patches(
            bytes(HEADER_BYTES) + b"abcdefgh",
            (
                NativePatch(IRAM_BASE, b"abcd", b"ABCD", "first"),
                NativePatch(IRAM_BASE, second_before, b"ABCD", "second"),
            ),
        )


def test_partial_overlap_rejected_in_any_order() -> None:
    patches = (
        NativePatch(IRAM_BASE, b"abcd", b"ABCD", "first"),
        NativePatch(IRAM_BASE + 2, b"cdef", b"CDEF", "second"),
    )
    for plan in (patches, tuple(reversed(patches))):
        with pytest.raises(ValueError, match="Overlapping"):
            apply_patches(bytes(HEADER_BYTES) + b"abcdefgh", plan)


@pytest.mark.parametrize(
    "before,after,error",
    [
        (b"", b"", "nonempty"),
        (b"abcd", b"X", "preserve"),
        (b"abcdx", b"ABCDE", "exceeds input"),
        (b"wxyz", b"ABCD", "Unexpected instructions"),
    ],
)
def test_invalid_patch_rejected(before: bytes, after: bytes, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        apply_patches(
            bytes(HEADER_BYTES) + b"abcd",
            [NativePatch(IRAM_BASE, before, after, "invalid")],
        )


@pytest.mark.parametrize(
    "address,size",
    [
        (IRAM_BASE - 1, 1),
        (IRAM_END - 1, 2),
        (DRAM_END - 1, 2),
        (DRAM_END, 1),
        (DRAM_BASE, 0),
        (DRAM_BASE, -1),
    ],
)
def test_whole_span_must_fit_one_initialized_region(address: int, size: int) -> None:
    with pytest.raises(ValueError, match="outside initialized"):
        runtime_offset(address, size)


def test_mapping_includes_last_initialized_byte() -> None:
    assert runtime_offset(IRAM_BASE, 1) == HEADER_BYTES
    assert runtime_offset(DRAM_BASE, 1) == DRAM_FILE
    assert runtime_offset(IRAM_END - 1, 1) == DRAM_FILE - 1
    assert runtime_offset(DRAM_END - 1, 1) == DRAM_FILE + DRAM_END - DRAM_BASE - 1


@pytest.mark.parametrize("delta", [-(1 << 25), -4, 0, 4, (1 << 25) - 4])
def test_arm_call_roundtrip_including_signed_limits(delta: int) -> None:
    address = DRAM_BASE
    word = struct.unpack("<I", arm_call(address, address + 8 + delta))[0]
    assert word >> 24 == 0xEB
    displacement = (word & 0xFFFFFF) << 2
    if displacement & (1 << 25):
        displacement -= 1 << 26
    assert address + 8 + displacement == address + 8 + delta


@pytest.mark.parametrize(
    "address,target",
    [
        (DRAM_BASE, DRAM_BASE + 8 + (1 << 25)),
        (DRAM_BASE, DRAM_BASE + 4 - (1 << 25)),
        (DRAM_BASE + 1, DRAM_BASE + 5),
        (DRAM_BASE, DRAM_BASE + 2),
        (-4, 0),
        (0, 1 << 32),
    ],
)
def test_arm_call_rejects_out_of_range_or_unaligned_targets(
    address: int, target: int
) -> None:
    with pytest.raises(ValueError):
        arm_call(address, target)


@pytest.mark.parametrize("value", [0, 255, 0xA10000, 0x100, 0x80000001])
def test_arm_immediate_roundtrip(value: int) -> None:
    encoded = arm_immediate(value)
    rotate = (encoded >> 8) * 2
    byte = encoded & 255
    assert ((byte >> rotate) | (byte << (32 - rotate))) & 0xFFFFFFFF == value


@pytest.mark.parametrize("value", [-1, 1 << 32, 0x12345678])
def test_unencodable_arm_immediate_rejected(value: int) -> None:
    with pytest.raises(ValueError):
        arm_immediate(value)
