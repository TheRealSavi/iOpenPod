"""PhotosDB parser, writer, and builder contracts."""

import base64
from dataclasses import replace
from pathlib import Path

import pytest

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_auxiliary_mhod,
    new_container_mhod,
    new_photos_chunk,
    new_PhotosDB,
    new_string_mhod,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhba import DEFINITION as MHBA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhif import DEFINITION as MHIF_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    EMPTY_MHAF_BODY,
    MhodOpaquePayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "PhotosDB"


def _golden_fixture() -> bytes:
    return base64.b64decode(
        (FIXTURE_DIR / "original-photo-library.b64")
        .read_text(encoding="ascii")
        .strip(),
        validate=True,
    )


def test_original_photo_database_round_trips_byte_exactly() -> None:
    fixture = _golden_fixture()

    assert write_PhotosDB(parse_PhotosDB(fixture)) == fixture


def test_unknown_root_data_and_source_suffix_round_trip_byte_exactly() -> None:
    fixture = bytearray(_golden_fixture())
    fixture[0x44:0x4C] = b"PHOTO-DB"
    original = bytes(fixture) + b"FUTURE-PHOTO-SUFFIX"

    database = parse_PhotosDB(original)

    assert database.raw_header[0x44:0x4C] == b"PHOTO-DB"
    assert database.raw_source_suffix == b"FUTURE-PHOTO-SUFFIX"
    assert write_PhotosDB(database) == original


def test_parses_photo_database_root_and_datasets() -> None:
    database = parse_PhotosDB(_golden_fixture())

    assert type(database.header) is MhfdHeader
    assert database.header.unk_mhfd_0x10 == 6
    assert database.header.child_count == 3
    assert database.header.next_mhii_id == 103
    assert tuple(
        child.header.dataset_type
        for child in database.children
        if isinstance(child.header, MhsdHeader)
    ) == (1, 2, 3)
    assert tuple(
        child.children[0].generic_header.header_marker for child in database.children
    ) == (b"mhli", b"mhla", b"mhlf")


def test_parses_photo_representations_and_paths() -> None:
    database = parse_PhotosDB(_golden_fixture())
    image = database.find_chunks(MhiiHeader)[0].chunk
    representations = image.find_chunks(MhodHeader)

    assert image.header.image_id == 100
    assert image.header.original_date == 1_700_000_000
    assert image.header.exif_taken_date == 1_699_999_000
    assert image.header.source_image_size == 34_567
    assert tuple(item.chunk.header.mhod_type for item in representations) == (5, 2, 2)

    locations = tuple(
        item.chunk.payload_as(MhodContainerPayload).child for item in representations
    )
    assert tuple(location.header.format_id for location in locations) == (1, 1017, 1023)
    assert tuple(location.header.ithmb_offset for location in locations) == (0, 0, 8192)
    assert tuple(location.header.image_size for location in locations) == (
        30_001,
        4096,
        8192,
    )
    assert tuple(
        location.child_as(0, MhodHeader).payload_as(MhodStringPayload).value
        for location in locations
    ) == (
        ":Full Resolution:iOpenPod:Sunrise.jpg",
        ":Thumbs:F1017_1.ithmb",
        ":Thumbs:F1023_1.ithmb",
    )


def test_parses_photo_albums_membership_and_slideshow_fields() -> None:
    database = parse_PhotosDB(_golden_fixture())
    albums = database.find_chunks(MhbaHeader)

    assert tuple(album.chunk.header.album_id for album in albums) == (101, 102)
    assert tuple(album.chunk.header.album_type for album in albums) == (1, 2)
    assert tuple(
        album.find_chunks(MhodHeader)[0].chunk.payload_as(MhodStringPayload).value
        for album in albums
    ) == ("Photo Library", "Favorites")
    assert tuple(
        album.find_chunks(MhiaHeader)[0].chunk.header.image_id for album in albums
    ) == (100, 100)
    assert albums[1].chunk.header.play_music == 1
    assert albums[1].chunk.header.repeat == 1
    assert albums[1].chunk.header.show_titles == 1
    assert albums[1].chunk.header.slide_duration == 6000
    assert albums[1].chunk.header.transition_duration == 1000
    assert albums[1].chunk.header.previous_album_id == 101


def test_parses_photo_file_format_items() -> None:
    formats = parse_PhotosDB(_golden_fixture()).find_chunks(MhifHeader)

    assert tuple(item.chunk.header.format_id for item in formats) == (1017, 1023)
    assert tuple(item.chunk.header.image_size for item in formats) == (4096, 8192)


def test_writer_edits_a_photo_album_without_rebuilding_its_ancestors() -> None:
    database = parse_PhotosDB(_golden_fixture())
    album = database.find_chunks(MhbaHeader)[1]
    name = album.find_chunks(MhodHeader)[0]
    edited_name = name.chunk.edit_payload(
        MhodStringPayload,
        lambda payload: replace(payload, value="Sunsets"),
    )

    reparsed = parse_PhotosDB(write_PhotosDB(database.replace_chunk(name, edited_name)))
    edited_album = reparsed.find_chunks(MhbaHeader)[1]

    assert (
        edited_album.find_chunks(MhodHeader)[0]
        .chunk.payload_as(MhodStringPayload)
        .value
        == "Sunsets"
    )
    assert edited_album.chunk.header.previous_album_id == 101
    assert reparsed.find_chunks(MhiiHeader)[0].chunk.header.source_image_size == 34_567


def test_builder_constructs_a_typed_photo_database_without_a_template() -> None:
    path = new_string_mhod(PhotosMhodType.FILE_NAME, ":Thumbs:F1017_1.ithmb")
    location = new_photos_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1017,
            image_size=4096,
            image_height=176,
            image_width=220,
            image_size_2=4096,
        ),
        children=(path,),
    )
    image = new_photos_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=100, source_image_size=34_567),
        children=(new_container_mhod(PhotosMhodType.THUMBNAIL_IMAGE, location),),
    )
    album = new_photos_chunk(
        MHBA_DEFINITION,
        MhbaHeader(album_id=101, album_type=1),
        children=(
            new_string_mhod(PhotosMhodType.ALBUM_NAME, "Photo Library"),
            new_photos_chunk(MHIA_DEFINITION, MhiaHeader(image_id=100)),
        ),
    )
    file_item = new_photos_chunk(
        MHIF_DEFINITION,
        MhifHeader(format_id=1017, image_size=4096),
    )

    reparsed = parse_PhotosDB(
        write_PhotosDB(
            new_PhotosDB(
                next_mhii_id=102,
                unk_mhfd_0x10=6,
                image_items=(image,),
                photo_albums=(album,),
                file_items=(file_item,),
            )
        )
    )

    assert type(reparsed.header) is MhfdHeader
    assert reparsed.find_chunks(MhiiHeader)[0].chunk.header.image_id == 100
    assert reparsed.find_chunks(MhbaHeader)[0].chunk.header.album_type == 1
    assert reparsed.find_chunks(MhifHeader)[0].chunk.header.format_id == 1017


def test_contextual_type_2_album_string_uses_the_photo_parser_registry() -> None:
    album = new_photos_chunk(
        MHBA_DEFINITION,
        MhbaHeader(album_id=100, album_type=1),
        children=(new_string_mhod(PhotosMhodType.THUMBNAIL_IMAGE, "Camera Roll"),),
    )
    database = new_PhotosDB(
        next_mhii_id=101,
        unk_mhfd_0x10=6,
        photo_albums=(album,),
    )

    reparsed = parse_PhotosDB(write_PhotosDB(database))
    title = reparsed.find_chunks(MhbaHeader)[0].find_chunks(MhodHeader)[0].chunk

    assert title.payload_as(MhodStringPayload).value == "Camera Roll"


def test_auxiliary_mhod_uses_the_shared_opaque_representation() -> None:
    image = new_photos_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=100),
        children=(new_auxiliary_mhod(),),
    )

    reparsed = parse_PhotosDB(
        write_PhotosDB(
            new_PhotosDB(
                next_mhii_id=101,
                unk_mhfd_0x10=6,
                image_items=(image,),
            )
        )
    )
    auxiliary = reparsed.find_chunks(MhodHeader)[0].chunk

    assert auxiliary.payload_as(MhodOpaquePayload).data == EMPTY_MHAF_BODY


def test_artworkdb_and_photosdb_roots_are_nominally_distinct() -> None:
    photo_database = parse_PhotosDB(_golden_fixture())
    artwork_database = parse_ArtworkDB(_golden_fixture())

    with pytest.raises(TypeError, match="requires MhfdHeader"):
        write_ArtworkDB(photo_database)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="requires MhfdHeader"):
        write_PhotosDB(artwork_database)  # type: ignore[arg-type]
