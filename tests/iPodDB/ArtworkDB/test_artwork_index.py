"""Application-facing projections from the lossless ArtworkDB document."""

from dataclasses import replace

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
    new_string_mhod,
)
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


def test_builds_indexed_track_and_ithmb_locations_from_typed_chunks() -> None:
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            ithmb_offset=4096,
            image_size=204_800,
            image_height=320,
            image_width=320,
            image_size_2=204_800,
        ),
        children=(
            new_string_mhod(
                ArtworkMhodType.FILE_NAME,
                ":F1060_1.ithmb",
            ),
        ),
    )
    image_item = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(
            image_id=64,
            db_track_id_ref=0x0102030405060708,
            source_image_size=987_654,
        ),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name),),
    )
    document = parse_ArtworkDB(
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                image_items=(image_item,),
            )
        )
    )

    index = build_artwork_index(document)
    item = index.item_for_image_id(64)

    assert item is not None
    assert index.item_for_db_track_id(0x0102030405060708) is item
    assert item.source_image_size == 987_654
    assert item.locations == (item.locations[0],)
    assert item.locations[0].file_name == ":F1060_1.ithmb"
    assert item.locations[0].format_id == 1060
    assert item.locations[0].offset == 4096
    assert item.locations[0].byte_length == 204_800
    assert item.locations[0].width == 320
    assert item.locations[0].height == 320


def test_omits_an_unbounded_ithmb_location_from_the_safe_index() -> None:
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            ithmb_offset=4096,
            image_size=0,
            image_height=320,
            image_width=320,
            image_size_2=0,
        ),
    )
    image_item = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=64, db_track_id_ref=7, source_image_size=100),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name),),
    )
    document = parse_ArtworkDB(
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                image_items=(image_item,),
            )
        )
    )

    item = build_artwork_index(document).item_for_image_id(64)

    assert item is not None
    assert item.locations == ()


def test_one_invalid_format_does_not_hide_other_covers_or_destroy_its_record() -> None:
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            image_size=204_800,
            image_size_2=204_800,
            image_height=320,
            image_width=320,
        ),
        children=(new_string_mhod(ArtworkMhodType.FILE_NAME, ":F1060_1.ithmb"),),
    )
    invalid = replace(image_name, header=replace(image_name.header, format_id=0))
    first = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=100, db_track_id_ref=1),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, invalid),),
    )
    second = replace(
        first,
        header=replace(first.header, image_id=101, db_track_id_ref=2),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name),),
    )
    source = write_ArtworkDB(
        new_ArtworkDB(next_mhii_id=102, unk_mhfd_0x10=6, image_items=(first, second))
    )
    document = parse_ArtworkDB(source)

    index = build_artwork_index(document)

    missing = index.item_for_image_id(100)
    surviving = index.item_for_image_id(101)
    assert missing is not None
    assert missing.locations == ()
    assert surviving is not None
    assert len(surviving.locations) == 1
    assert index.item_for_db_track_id(2) is surviving
    assert write_ArtworkDB(document) == source
