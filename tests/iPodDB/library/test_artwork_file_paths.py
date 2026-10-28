"""Write-time filename evidence includes retained records outside display projection."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import COVER, with_shared_artwork

from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_ArtworkDB, new_string_mhod
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


@pytest.mark.parametrize(
    "kind", [ArtworkMhodType.THUMBNAIL_IMAGE, ArtworkMhodType.FULL_RES_IMAGE]
)
def test_file_paths_include_orphan_records_and_non_display_allocations(
    kind: ArtworkMhodType,
) -> None:
    source, _file = with_shared_artwork()
    raw = source.serialize().artwork
    assert raw is not None
    row = parse_ArtworkDB(raw).find_chunks(MhiiHeader)[0].chunk
    container = next(
        child
        for child in row.children
        if isinstance(child.payload, MhodContainerPayload)
    )
    assert isinstance(container.header, MhodHeader)
    assert isinstance(container.payload, MhodContainerPayload)
    orphan_location = replace(
        container.payload.child,
        header=replace(
            container.payload.child.header,
            format_id=0,
            image_size=0,
            image_size_2=32,
        ),
        children=(
            new_string_mhod(ArtworkMhodType.FILE_NAME, ":hidden:reserved.ithmb"),
        ),
    )
    orphan = replace(
        row,
        header=replace(row.header, image_id=222, db_track_id_ref=0),
        children=(
            replace(
                container,
                header=replace(container.header, mhod_type=kind),
                payload=replace(container.payload, child=orphan_location),
            ),
        ),
    )
    original = write_ArtworkDB(
        new_ArtworkDB(next_mhii_id=223, unk_mhfd_0x10=2, image_items=(row, orphan))
    )
    retained = source.with_artwork(original)

    assert retained.artwork_file_paths() == (
        "iPod_Control/Artwork/F1055_1.ithmb",
        "iPod_Control/Artwork/hidden/reserved.ithmb",
    )
    assert retained.artwork_read(222, (COVER,), 4) is None
    assert all(track.artwork_id != 222 for track in retained.snapshot.tracks)
    assert retained.serialize().artwork == original
