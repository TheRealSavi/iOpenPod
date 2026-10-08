"""Photos recover only image counts proved by complete retained MHII records."""

import base64
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_photos_chunk,
    new_PhotosDB,
    new_string_mhod,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.parser.repair_PhotosDB import repair_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhba import DEFINITION as MHBA
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB


def _source() -> tuple[bytes, int]:
    path = Path(__file__).parents[2] / "fixtures/PhotosDB/original-photo-library.b64"
    database = parse_PhotosDB(base64.b64decode(path.read_text(encoding="ascii")))
    dataset = database.children[0]
    images = dataset.children[0]
    first = images.child_as(0, MhiiHeader)
    second = replace(first, header=replace(first.header, image_id=103))
    database = replace(
        database,
        children=(
            replace(dataset, children=(images.append_child(second),)),
            *database.children[1:],
        ),
        raw_source_suffix=b"retained photo source suffix",
    )
    source = write_PhotosDB(database)
    return source, parse_PhotosDB(source).children[0].children[0].offset


@pytest.mark.parametrize("declared", (0, 1, 3, 0xFFFFFFFF))
def test_repairs_photo_count_without_rewriting_albums_or_unknown_data(
    declared: int,
) -> None:
    expected, offset = _source()
    damaged = bytearray(expected)
    struct.pack_into("<I", damaged, offset + 8, declared)

    repaired = repair_PhotosDB(damaged)

    assert type(repaired.document.header) is MhfdHeader
    assert repaired.data == expected
    assert write_PhotosDB(repaired.document) == expected
    assert tuple(
        row.chunk.header.image_id for row in repaired.document.find_chunks(MhiiHeader)
    ) == (100, 103)
    assert len(repaired.repairs) == 1
    assert (
        repaired.repairs[0].list_offset,
        repaired.repairs[0].previous_count,
        repaired.repairs[0].corrected_count,
    ) == (offset, declared, 2)
    assert struct.unpack_from("<I", damaged, offset + 8)[0] == declared


def test_healthy_photo_repair_reuses_original_bytes_and_is_idempotent() -> None:
    source, _ = _source()

    repaired = repair_PhotosDB(source)

    assert repaired.data is source
    assert not repaired.repairs
    assert repair_PhotosDB(repaired.data) == repaired


def test_strict_photo_parser_retains_wrong_count_until_explicit_repair() -> None:
    source, offset = _source()
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, offset + 8, 0)

    assert write_PhotosDB(parse_PhotosDB(damaged)) == damaged
    assert not parse_PhotosDB(damaged).find_chunks(MhiiHeader)


@pytest.mark.parametrize(
    "damage", ("opaque_suffix", "incomplete_image", "duplicate_id", "crosses_dataset")
)
def test_ambiguous_hidden_photo_evidence_does_not_authorize_repair(damage: str) -> None:
    source, offset = _source()
    database = parse_PhotosDB(source)
    hidden = database.find_chunks(MhiiHeader)[1].chunk
    if damage == "opaque_suffix":
        dataset = database.children[0]
        source = write_PhotosDB(
            replace(
                database,
                children=(
                    replace(dataset, raw_trailing_data=b"future photo data"),
                    *database.children[1:],
                ),
            )
        )
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, offset + 8, 1)
    if damage == "incomplete_image":
        struct.pack_into("<I", damaged, hidden.offset + 0x0C, 100)
    elif damage == "duplicate_id":
        struct.pack_into("<I", damaged, hidden.offset + 0x10, 100)
    elif damage == "crosses_dataset":
        struct.pack_into(
            "<I",
            damaged,
            hidden.offset + 8,
            hidden.generic_header.length_or_child_count + 1,
        )

    repaired = repair_PhotosDB(damaged)

    assert not repaired.repairs
    assert repaired.data == damaged
    assert write_PhotosDB(repaired.document) == damaged
    assert len(repaired.document.find_chunks(MhiiHeader)) == 1


def test_photos_repair_keeps_its_contextual_album_mhod_parser() -> None:
    expected = write_PhotosDB(
        new_PhotosDB(
            next_mhii_id=102,
            unk_mhfd_0x10=6,
            image_items=(new_photos_chunk(MHII, MhiiHeader(image_id=100)),),
            photo_albums=(
                new_photos_chunk(
                    MHBA,
                    MhbaHeader(album_id=101, album_type=1),
                    children=(
                        new_string_mhod(PhotosMhodType.THUMBNAIL_IMAGE, "Camera Roll"),
                    ),
                ),
            ),
        )
    )
    offset = parse_PhotosDB(expected).children[0].children[0].offset
    damaged = bytearray(expected)
    struct.pack_into("<I", damaged, offset + 8, 0)

    repaired = repair_PhotosDB(damaged)

    assert repaired.data == expected
    album = repaired.document.find_chunks(MhbaHeader)[0].chunk
    assert album.children[0].payload_as(MhodStringPayload).value == "Camera Roll"


def test_photos_repair_never_uses_source_suffix_as_another_photo() -> None:
    source, offset = _source()
    image = parse_PhotosDB(source).find_chunks(MhiiHeader)[0].chunk
    source += source[
        image.offset : image.offset + image.generic_header.length_or_child_count
    ]
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, offset + 8, 3)

    repaired = repair_PhotosDB(damaged)

    assert repaired.data == source
    assert repaired.repairs[0].corrected_count == 2


def test_photo_repair_cannot_accept_a_truncated_root() -> None:
    source, _ = _source()
    length = struct.unpack_from("<I", source, 8)[0]

    with pytest.raises(ValueError, match="extends past end of data"):
        repair_PhotosDB(source[: length - 1])
