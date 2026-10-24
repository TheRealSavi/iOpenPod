"""Genius graph identity is an iPod diagnostic, distinct from Track/category IDs."""

import struct

import pytest
from tests.iPodDB.binary_fixtures import (
    dataset,
    itunes_database,
    length_chunk,
    list_chunk,
)

from iPodDB.library import IPodLibrary, IPodTrackDetails


@pytest.mark.parametrize("header_size", [0x1F8, 0x270])
def test_library_exposes_genius_identity_without_changing_original_bytes(
    header_size: int,
) -> None:
    fields = bytearray(header_size - 12)
    struct.pack_into("<I", fields, 0x10 - 12, 7)
    struct.pack_into("<Q", fields, 0x70 - 12, 19)
    struct.pack_into("<I", fields, 0x98 - 12, 23)
    struct.pack_into("<Q", fields, 0x1E4 - 12, 0xFEDCBA9876543210)
    data = itunes_database(
        dataset(
            1,
            list_chunk(
                b"mhlt", length_chunk(b"mhit", header_size, fields=bytes(fields))
            ),
        )
    )
    library = IPodLibrary.parse(data)
    (track,) = library.snapshot.tracks
    assert track.track_id == 7
    assert track.ipod is not None
    assert track.ipod.db_track_id == 19
    assert track.ipod.genius_category_id == 23
    assert track.ipod.genius_id == 0xFEDCBA9876543210
    assert library.serialize().itunes == data


def test_older_track_layout_exposes_no_invented_genius_identity() -> None:
    data = itunes_database(dataset(1, list_chunk(b"mhlt", length_chunk(b"mhit", 0x9C))))
    library = IPodLibrary.parse(data)
    (track,) = library.snapshot.tracks
    assert track.ipod is not None
    assert track.ipod.genius_id == 0
    assert IPodTrackDetails().genius_id == 0
    assert library.serialize().itunes == data
