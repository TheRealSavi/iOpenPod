"""Malformed native resource directories cannot supply build-time pointers."""

import struct

import pytest
from scripts.firmware.classic_resources import (
    UI_BANK_OFFSET,
    UI_DIRECTORY_BYTES,
    stock_resource_locations,
    stock_resources,
)


@pytest.fixture
def bank() -> bytearray:
    # A complete 27-kind directory, two IDs deliberately sharing one payload.
    image = bytearray(UI_BANK_OFFSET + UI_DIRECTORY_BYTES + 4)
    struct.pack_into("<III", image, UI_BANK_OFFSET, 3, 97056, 27)
    for index in range(27):
        kind = int.from_bytes(f"{index:04d}".encode("ascii"), "big")
        struct.pack_into(
            "<4I",
            image,
            UI_BANK_OFFSET + 12 + index * 16,
            kind,
            2 if index == 0 else 0,
            0,
            444,
        )
    struct.pack_into("<6I", image, UI_BANK_OFFSET + 444, 1, 0, 4, 2, 0, 4)
    image[-4:] = b"data"
    return image


def test_distinct_ids_may_share_payload(bank: bytearray) -> None:
    assert stock_resources(bytes(bank)) == {("0000", 1): b"data", ("0000", 2): b"data"}
    spans = stock_resource_locations(bytes(bank))
    assert spans["0000", 1] == spans["0000", 2] == (len(bank) - 4, 4)


@pytest.mark.parametrize(
    "size",
    [0, UI_BANK_OFFSET, UI_BANK_OFFSET + 11, UI_BANK_OFFSET + UI_DIRECTORY_BYTES - 1],
)
def test_truncated_directory_rejected(bank: bytearray, size: int) -> None:
    with pytest.raises(ValueError, match="Truncated"):
        stock_resource_locations(bytes(bank[:size]))


@pytest.mark.parametrize(
    "offset,value,error",
    [
        (0, 4, "Unexpected"),
        (4, 97055, "Unexpected"),
        (8, 26, "Unexpected"),
        (12, 0xFF000000, "Invalid UI resource type"),
        (28, 0x30303030, "Duplicate UI resource type"),
        (24, 443, "index exceeds"),
        (24, 97056, "index exceeds"),
        (16, 0xFFFFFFFF, "index exceeds"),
        (448, 5, "Invalid UI resource entry"),
        (452, 5, "Invalid UI resource entry"),
        (456, 1, "Invalid UI resource entry"),
    ],
)
def test_invalid_directory_entry_rejected(
    bank: bytearray, offset: int, value: int, error: str
) -> None:
    struct.pack_into("<I", bank, UI_BANK_OFFSET + offset, value)
    with pytest.raises(ValueError, match=error):
        stock_resource_locations(bytes(bank))
