"""Recovery must expose retained images without changing any image or pixel bytes."""

import struct
from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
    new_string_mhod,
)
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.parser.repair_ArtworkDB import repair_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


def _source() -> tuple[bytes, int]:
    location = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            ithmb_offset=0,
            image_size=204_800,
            image_size_2=204_800,
            image_width=320,
            image_height=320,
        ),
        children=(new_string_mhod(ArtworkMhodType.FILE_NAME, ":F1060_1.ithmb"),),
    )
    image = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=100, db_track_id_ref=7),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, location),),
    )
    database = new_ArtworkDB(
        next_mhii_id=102,
        unk_mhfd_0x10=6,
        image_items=(
            image,
            replace(image, header=replace(image.header, image_id=101)),
        ),
    )
    source = write_ArtworkDB(database) + b"retained source suffix"
    parsed = parse_ArtworkDB(source)
    return source, parsed.children[0].children[0].offset


@pytest.mark.parametrize("recorded_count", (0, 1, 3, 0xFFFFFFFF))
def test_recovers_all_covers_from_a_wrong_image_count(recorded_count: int) -> None:
    expected, list_offset = _source()
    damaged = bytearray(expected)
    struct.pack_into("<I", damaged, list_offset + 8, recorded_count)

    recovered = repair_ArtworkDB(damaged)

    assert [
        item.image_id for item in build_artwork_index(recovered.document).items
    ] == [
        100,
        101,
    ]
    assert recovered.data == expected
    assert write_ArtworkDB(recovered.document) == expected
    assert len(recovered.repairs) == 1
    assert recovered.repairs[0].list_offset == list_offset
    assert recovered.repairs[0].previous_count == recorded_count
    assert recovered.repairs[0].corrected_count == 2
    assert struct.unpack_from("<I", damaged, list_offset + 8)[0] == recorded_count


def test_lossless_parser_keeps_an_understated_count_until_explicit_repair() -> None:
    expected, list_offset = _source()
    damaged = bytearray(expected)
    struct.pack_into("<I", damaged, list_offset + 8, 0)

    assert write_ArtworkDB(parse_ArtworkDB(damaged)) == damaged


def test_recovery_is_idempotent_for_a_valid_database() -> None:
    source, _ = _source()

    recovered = repair_ArtworkDB(source)

    assert recovered.data == source
    assert recovered.repairs == ()
    assert repair_ArtworkDB(recovered.data) == recovered


def test_repair_preserves_unknown_headers_payloads_and_source_suffix() -> None:
    source, list_offset = _source()
    retained = bytearray(source)
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[0]
    retained[image.offset + 0x70 : image.offset + 0x74] = b"keep"
    retained[list_offset + 0x40 : list_offset + 0x44] = b"list"
    damaged = bytearray(retained)
    struct.pack_into("<I", damaged, list_offset + 8, 0)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == retained
    assert write_ArtworkDB(recovered.document) == retained


def test_recovery_does_not_promote_an_opaque_dataset_suffix_to_an_image() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    dataset = document.children[0]
    with_suffix = replace(dataset, raw_trailing_data=b"unknown future content")
    retained = write_ArtworkDB(
        replace(document, children=(with_suffix, *document.children[1:]))
    )
    damaged = bytearray(retained)
    struct.pack_into("<I", damaged, list_offset + 8, 0)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == damaged
    assert recovered.repairs == ()
    assert write_ArtworkDB(recovered.document) == damaged


def test_recovery_does_not_claim_a_malformed_hidden_image_is_complete() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[1]
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, list_offset + 8, 1)
    struct.pack_into("<I", damaged, image.offset + 0x0C, 9)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == damaged
    assert recovered.repairs == ()
    assert len(build_artwork_index(recovered.document).items) == 1


def test_recovery_does_not_promote_an_ambiguous_hidden_duplicate_image_id() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[1]
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, list_offset + 8, 1)
    struct.pack_into("<I", damaged, image.offset + 0x10, 100)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == damaged
    assert recovered.repairs == ()
    assert [
        item.image_id for item in build_artwork_index(recovered.document).items
    ] == [100]
    assert write_ArtworkDB(recovered.document) == damaged


def test_ambiguous_duplicate_images_do_not_make_an_overcount_repairable() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[1]
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, list_offset + 8, 3)
    struct.pack_into("<I", damaged, image.offset + 0x10, 100)

    with pytest.raises(ValueError, match="child must use b'mhii'"):
        repair_ArtworkDB(damaged)


def test_recovery_does_not_create_duplicate_identities_across_image_datasets() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    dataset = document.children[0]
    image_list = dataset.children[0]
    second_dataset = replace(
        dataset,
        children=(replace(image_list, children=(image_list.children[0],)),),
    )
    damaged = bytearray(
        write_ArtworkDB(
            replace(
                document, children=(dataset, second_dataset, *document.children[1:])
            )
        )
    )
    struct.pack_into("<I", damaged, list_offset + 8, 0)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == damaged
    assert recovered.repairs == ()
    assert [
        item.image_id for item in build_artwork_index(recovered.document).items
    ] == [100]


def test_recovery_does_not_read_an_image_across_its_dataset_boundary() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[1]
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, list_offset + 8, 1)
    struct.pack_into(
        "<I", damaged, image.offset + 8, image.generic_header.length_or_child_count + 1
    )

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == damaged
    assert recovered.repairs == ()


def test_recovery_never_uses_a_source_suffix_as_an_additional_image() -> None:
    source, list_offset = _source()
    document = parse_ArtworkDB(source)
    image = document.children[0].children[0].children[0]
    duplicate = source[
        image.offset : image.offset + image.generic_header.length_or_child_count
    ]
    damaged = bytearray(source + duplicate)
    struct.pack_into("<I", damaged, list_offset + 8, 3)

    recovered = repair_ArtworkDB(damaged)

    assert recovered.data == source + duplicate
    assert recovered.repairs[0].corrected_count == 2
    assert len(build_artwork_index(recovered.document).items) == 2


def test_recovery_still_rejects_a_truncated_root() -> None:
    source, _ = _source()
    root_length = struct.unpack_from("<I", source, 8)[0]

    with pytest.raises(ValueError, match="extends past end of data"):
        repair_ArtworkDB(source[: root_length - 1])


def test_writer_counts_new_and_recovered_images_without_duplicating_retained_bytes() -> (
    None
):
    source, list_offset = _source()
    damaged = bytearray(source)
    struct.pack_into("<I", damaged, list_offset + 8, 0)
    recovered = repair_ArtworkDB(damaged)
    dataset = recovered.document.children[0]
    image_list = dataset.children[0]
    image = image_list.child_as(0, MhiiHeader)
    new_image = replace(image, header=replace(image.header, image_id=102))
    changed = replace(image_list, children=(*image_list.children, new_image))
    candidate = replace(
        recovered.document,
        children=(
            replace(dataset, children=(changed,)),
            *recovered.document.children[1:],
        ),
    )

    serialized = write_ArtworkDB(candidate)
    reparsed = parse_ArtworkDB(serialized)

    assert struct.unpack_from("<I", serialized, list_offset + 8)[0] == 3
    assert [item.image_id for item in build_artwork_index(reparsed).items] == [
        100,
        101,
        102,
    ]
    assert serialized.count(b"mhii") == 3
    assert reparsed.raw_source_suffix == recovered.document.raw_source_suffix
