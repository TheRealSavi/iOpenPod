from __future__ import annotations

import struct

from iopenpod.device import capabilities_for_family_gen
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd


def _mhsd_types(data: bytes) -> list[int]:
    header_length = struct.unpack_from("<I", data, 4)[0]
    child_count = struct.unpack_from("<I", data, 0x14)[0]
    offset = header_length
    types: list[int] = []

    for _ in range(child_count):
        assert data[offset:offset + 4] == b"mhsd"
        total_length = struct.unpack_from("<I", data, offset + 8)[0]
        types.append(struct.unpack_from("<I", data, offset + 12)[0])
        offset += total_length

    return types


def test_reference_mhsd_shape_does_not_gain_artist_dataset() -> None:
    data = write_mhbd(
        [],
        reference_info={
            "version": 0x73,
            "mhsd_types": {1, 2, 3, 4, 5},
            "mhsd_order": [4, 1, 3, 2, 5],
        },
        capabilities=capabilities_for_family_gen("iPod Mini", "2nd Gen"),
    )

    assert _mhsd_types(data) == [4, 1, 3, 2, 5]


def test_legacy_device_strips_previously_generated_artist_dataset() -> None:
    data = write_mhbd(
        [],
        reference_info={
            "version": 0x73,
            "mhsd_types": {1, 2, 3, 4, 5, 8},
            "mhsd_order": [4, 1, 3, 2, 5, 8],
        },
        capabilities=capabilities_for_family_gen("iPod Mini", "2nd Gen"),
    )

    assert _mhsd_types(data) == [4, 1, 3, 2, 5]


def test_modern_reference_keeps_artist_dataset() -> None:
    data = write_mhbd(
        [],
        reference_info={
            "version": 0x30,
            "mhsd_types": {1, 2, 3, 4, 5, 8},
            "mhsd_order": [4, 1, 3, 2, 5, 8],
        },
    )

    assert _mhsd_types(data) == [4, 1, 3, 2, 5, 8]


def test_reference_type3_playlist_shape_writes_type2_companion() -> None:
    data = write_mhbd(
        [],
        reference_info={
            "version": 0x30,
            "mhsd_types": {1, 3, 4, 5},
            "mhsd_order": [4, 1, 3, 5],
        },
    )

    assert _mhsd_types(data) == [4, 1, 3, 2, 5]


def test_write_mhbd_preserves_reference_platform_flag() -> None:
    data = write_mhbd([], reference_info={"platform": 1})

    assert struct.unpack_from("<H", data, 0x20)[0] == 1
