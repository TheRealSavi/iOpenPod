import base64
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.binary_fixtures import artwork_database as _artworkdb
from tests.iPodDB.binary_fixtures import artwork_string_mhod as _mhod_string
from tests.iPodDB.binary_fixtures import photo_album as _photo_album

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
    new_string_mhod,
)
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhaf import MhafHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhba import DEFINITION as MHBA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import DEFINITION as MHIF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkDatasetType, ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import (
    write_ArtworkDB,
)
from iPodDB.shared.chunk import RawPayload, UnknownChunkHeader

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "ArtworkDB"


def _golden_fixture(name: str) -> bytes:
    return base64.b64decode(
        (FIXTURE_DIR / name).read_text(encoding="ascii").strip(),
        validate=True,
    )


def _empty_list(marker: bytes) -> bytes:
    header = bytearray(92)
    struct.pack_into("<4sII", header, 0, marker, len(header), 0)
    return bytes(header)


def _dataset(dataset_type: int | ArtworkDatasetType, child: bytes) -> bytes:
    header = bytearray(96)
    struct.pack_into(
        "<4sIIH",
        header,
        0,
        b"mhsd",
        len(header),
        len(header) + len(child),
        dataset_type,
    )
    struct.pack_into("<H", header, 0x0E, 0xBEEF)
    return bytes(header) + child


def _empty_artworkdb() -> bytes:
    return _artworkdb(
        _dataset(ArtworkDatasetType.IMAGE_LIST, _empty_list(b"mhli")),
        _dataset(ArtworkDatasetType.PHOTO_ALBUM_LIST, _empty_list(b"mhla")),
        _dataset(ArtworkDatasetType.FILE_LIST, _empty_list(b"mhlf")),
    )


def _mhod_container(mhod_type: int, child: bytes) -> bytes:
    header = bytearray(24)
    struct.pack_into(
        "<4sIIH",
        header,
        0,
        b"mhod",
        len(header),
        len(header) + len(child),
        mhod_type,
    )
    return bytes(header) + child


def _image_name() -> bytes:
    filename = _mhod_string(3, ":F1060_1.ithmb")
    header = bytearray(76)
    struct.pack_into(
        "<4sII",
        header,
        0,
        b"mhni",
        len(header),
        len(header) + len(filename),
    )
    struct.pack_into("<IIII", header, 0x0C, 1, 1060, 4096, 20000)
    struct.pack_into("<hhHH", header, 0x1C, 1, 2, 100, 200)
    struct.pack_into("<II", header, 0x24, 7, 20000)
    return bytes(header) + filename


def _image_item(container_type: int = 2) -> bytes:
    thumbnail = _mhod_container(container_type, _image_name())
    header = bytearray(152)
    struct.pack_into(
        "<4sII",
        header,
        0,
        b"mhii",
        len(header),
        len(header) + len(thumbnail),
    )
    struct.pack_into("<IIQ", header, 0x0C, 1, 64, 0x0102030405060708)
    struct.pack_into("<I", header, 0x20, 80)
    struct.pack_into("<I", header, 0x30, 123456)
    return bytes(header) + thumbnail


def _file_item() -> bytes:
    filename = _mhod_string(3, ":F1060_1.ithmb")
    header = bytearray(124)
    struct.pack_into(
        "<4sII",
        header,
        0,
        b"mhif",
        len(header),
        len(header) + len(filename),
    )
    struct.pack_into("<III", header, 0x0C, 1, 1060, 20000)
    return bytes(header) + filename


def test_parses_the_three_artworkdb_datasets_through_the_public_interface() -> None:
    database = parse_ArtworkDB(_empty_artworkdb())

    assert isinstance(database.header, MhfdHeader)
    assert database.header.child_count == 3
    assert database.header.next_mhii_id == 64
    assert database.header.unk_mhfd_0x0c == 11
    assert database.header.unk_mhfd_0x10 == 2
    assert database.header.unk_mhfd_0x18 == 12
    assert database.header.unk_mhfd_0x20 == 0x0102030405060708
    assert database.header.unk_mhfd_0x28 == 0x1112131415161718
    assert database.header.unk_mhfd_0x30 == 2
    assert database.header.unk_mhfd_0x34 == 13
    assert database.header.unk_mhfd_0x38 == 14
    assert database.header.unk_mhfd_0x3c == 15
    assert database.header.unk_mhfd_0x40 == 16
    assert tuple(child.generic_header.header_marker for child in database.children) == (
        b"mhsd",
        b"mhsd",
        b"mhsd",
    )
    assert tuple(
        child.header.dataset_type
        for child in database.children
        if isinstance(child.header, MhsdHeader)
    ) == (1, 2, 3)
    assert all(
        isinstance(child.header, MhsdHeader) and child.header.unk_mhsd_0x0e == 0xBEEF
        for child in database.children
    )
    assert tuple(
        child.children[0].generic_header.header_marker for child in database.children
    ) == (b"mhli", b"mhla", b"mhlf")


def test_parses_photo_album_metadata_and_membership() -> None:
    album = _photo_album(7, 64, "Road Trip")
    album_list = bytearray(92)
    struct.pack_into("<4sII", album_list, 0, b"mhla", len(album_list), 1)
    data = _artworkdb(
        _dataset(ArtworkDatasetType.PHOTO_ALBUM_LIST, bytes(album_list) + album)
    )

    database = parse_ArtworkDB(data)
    parsed_album = database.children[0].children[0].child_as(0, MhbaHeader)
    title = parsed_album.child_as(0, MhodHeader)
    member = parsed_album.child_as(1, MhiaHeader)

    assert parsed_album.header.album_id == 7
    assert parsed_album.header.mhod_child_count == 1
    assert parsed_album.header.image_child_count == 1
    assert parsed_album.header.album_type == 2
    assert parsed_album.header.unk_mhba_0x18 == 0x1111
    assert parsed_album.header.unk_mhba_0x1c == 0x2222
    assert parsed_album.header.play_music == 1
    assert parsed_album.header.repeat == 2
    assert parsed_album.header.random == 3
    assert parsed_album.header.show_titles == 4
    assert parsed_album.header.transition_direction == 5
    assert parsed_album.header.slide_duration == 6000
    assert parsed_album.header.transition_duration == 700
    assert parsed_album.header.unk_mhba_0x2c == b"ALBUMRAW"
    assert parsed_album.header.db_track_id_ref == 0x2122232425262728
    assert parsed_album.header.previous_album_id == 6
    assert title.prefix_as(MhodStringPrefix).string_byte_length == 9
    assert title.payload_as(MhodStringPayload).value == "Road Trip"
    assert title.payload_as(MhodStringPayload).trailing_data == b"\x00\x00\x00"
    assert member.header.image_id == 64


@pytest.mark.parametrize("container_type", [2, 5, 6])
def test_parses_image_items_and_nested_image_names(container_type: int) -> None:
    image = _image_item(container_type)
    image_list = bytearray(92)
    struct.pack_into("<4sII", image_list, 0, b"mhli", len(image_list), 1)
    data = _artworkdb(
        _dataset(ArtworkDatasetType.IMAGE_LIST, bytes(image_list) + image)
    )

    database = parse_ArtworkDB(data)
    parsed_image = database.children[0].children[0].child_as(0, MhiiHeader)
    container_mhod = parsed_image.child_as(0, MhodHeader)
    container = container_mhod.payload_as(MhodContainerPayload)
    image_name = container.child
    filename = image_name.child_as(0, MhodHeader)

    assert parsed_image.header.image_id == 64
    assert parsed_image.header.db_track_id_ref == 0x0102030405060708
    assert parsed_image.header.rating == 80
    assert parsed_image.header.source_image_size == 123456
    assert container_mhod.header.mhod_type == container_type
    assert isinstance(image_name.header, MhniHeader)
    assert image_name.header.format_id == 1060
    assert image_name.header.ithmb_offset == 4096
    assert image_name.header.image_size == 20000
    assert image_name.header.vertical_padding == 1
    assert image_name.header.horizontal_padding == 2
    assert image_name.header.image_height == 100
    assert image_name.header.image_width == 200
    assert image_name.header.image_size_2 == 20000
    assert filename.payload_as(MhodStringPayload).value == ":F1060_1.ithmb"


def test_parses_artwork_file_format_items() -> None:
    file_item = _file_item()
    file_list = bytearray(92)
    struct.pack_into("<4sII", file_list, 0, b"mhlf", len(file_list), 1)
    data = _artworkdb(
        _dataset(ArtworkDatasetType.FILE_LIST, bytes(file_list) + file_item)
    )

    database = parse_ArtworkDB(data)
    parsed_file = database.children[0].children[0].child_as(0, MhifHeader)
    filename = parsed_file.child_as(0, MhodHeader)

    assert parsed_file.header.child_count == 1
    assert parsed_file.header.format_id == 1060
    assert parsed_file.header.image_size == 20000
    assert filename.payload_as(MhodStringPayload).value == ":F1060_1.ithmb"


def test_unchanged_artworkdb_round_trip_is_byte_exact() -> None:
    original = bytearray(_empty_artworkdb())
    original[0x44:0x84] = bytes(range(64))

    database = parse_ArtworkDB(original)

    assert database.raw_header == bytes(original[:132])
    assert write_ArtworkDB(database) == original


def test_unknown_mhod_payload_is_unknown_data_not_a_parse_failure() -> None:
    opaque_body = b"\xde\xad\xbe\xef\x00"
    unknown = bytearray(24)
    struct.pack_into(
        "<4sIIH",
        unknown,
        0,
        b"mhod",
        len(unknown),
        len(unknown) + len(opaque_body),
        99,
    )
    image = bytearray(152)
    struct.pack_into(
        "<4sII",
        image,
        0,
        b"mhii",
        len(image),
        len(image) + len(unknown) + len(opaque_body),
    )
    struct.pack_into("<I", image, 0x0C, 1)
    image_list = bytearray(92)
    struct.pack_into("<4sII", image_list, 0, b"mhli", len(image_list), 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.IMAGE_LIST,
            bytes(image_list) + bytes(image) + bytes(unknown) + opaque_body,
        )
    )

    database = parse_ArtworkDB(original)
    mhod = database.children[0].children[0].children[0].child_as(0, MhodHeader)

    assert mhod.header.mhod_type == 99
    assert mhod.payload_as(MhodOpaquePayload).data == opaque_body
    assert write_ArtworkDB(database) == original


def test_known_opaque_mhaf_chunk_preserves_its_unknown_data() -> None:
    unknown_data = bytes(range(17))
    mhaf = (
        struct.pack(
            "<4sII",
            b"mhaf",
            12,
            12 + len(unknown_data),
        )
        + unknown_data
    )
    image = bytearray(152)
    struct.pack_into(
        "<4sII",
        image,
        0,
        b"mhii",
        len(image),
        len(image) + len(mhaf),
    )
    struct.pack_into("<I", image, 0x0C, 1)
    image_list = bytearray(92)
    struct.pack_into("<4sII", image_list, 0, b"mhli", len(image_list), 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.IMAGE_LIST,
            bytes(image_list) + bytes(image) + mhaf,
        )
    )

    database = parse_ArtworkDB(original)
    opaque = database.children[0].children[0].children[0].child_as(0, MhafHeader)

    assert opaque.payload_as(RawPayload).data == unknown_data
    assert write_ArtworkDB(database) == original


def test_unknown_length_delimited_chunk_is_preserved_as_unknown_data() -> None:
    unknown_data = b"future ArtworkDB data"
    unknown_chunk = (
        struct.pack(
            "<4sII",
            b"mhzz",
            12,
            12 + len(unknown_data),
        )
        + unknown_data
    )
    image = bytearray(152)
    struct.pack_into(
        "<4sII",
        image,
        0,
        b"mhii",
        len(image),
        len(image) + len(unknown_chunk),
    )
    struct.pack_into("<I", image, 0x0C, 1)
    image_list = bytearray(92)
    struct.pack_into("<4sII", image_list, 0, b"mhli", len(image_list), 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.IMAGE_LIST,
            bytes(image_list) + bytes(image) + unknown_chunk,
        )
    )

    database = parse_ArtworkDB(original)
    unknown = (
        database.children[0]
        .children[0]
        .children[0]
        .child_as(
            0,
            UnknownChunkHeader,
        )
    )

    assert unknown.generic_header.header_marker == b"mhzz"
    assert unknown.payload_as(RawPayload).data == unknown_data
    assert write_ArtworkDB(database) == original


def test_mhba_type_2_mhod_uses_the_observed_string_layout() -> None:
    bug_shaped_title = _mhod_string(2, "Camera Roll")
    album = bytearray(148)
    struct.pack_into(
        "<4sII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(bug_shaped_title),
    )
    struct.pack_into("<I", album, 0x0C, 1)
    album_list = bytearray(92)
    struct.pack_into("<4sII", album_list, 0, b"mhla", len(album_list), 1)
    data = _artworkdb(
        _dataset(
            ArtworkDatasetType.PHOTO_ALBUM_LIST,
            bytes(album_list) + bytes(album) + bug_shaped_title,
        )
    )

    database = parse_ArtworkDB(data)
    parsed_album = database.children[0].children[0].child_as(0, MhbaHeader)
    title = parsed_album.child_as(0, MhodHeader)

    assert title.header.mhod_type == 2
    assert title.payload_as(MhodStringPayload).value == "Camera Roll"


def test_writer_applies_a_known_field_edit_without_changing_unknown_data() -> None:
    original = _empty_artworkdb()
    database = parse_ArtworkDB(original)
    edited = replace(
        database,
        header=replace(database.header, next_mhii_id=65),
    )

    serialized = write_ArtworkDB(edited)
    reparsed = parse_ArtworkDB(serialized)

    assert reparsed.header.next_mhii_id == 65
    assert serialized[:0x1C] == original[:0x1C]
    assert serialized[0x20:] == original[0x20:]


def test_writer_applies_a_nested_chunk_field_edit() -> None:
    image = _image_item()
    image_list_bytes = bytearray(92)
    struct.pack_into("<4sII", image_list_bytes, 0, b"mhli", 92, 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.IMAGE_LIST,
            bytes(image_list_bytes) + image,
        )
    )
    database = parse_ArtworkDB(original)
    dataset = database.children[0]
    image_list = dataset.children[0]
    parsed_image = image_list.child_as(0, MhiiHeader)
    edited_image = replace(
        parsed_image,
        header=replace(parsed_image.header, image_id=65),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(image_list, children=(edited_image,)),),
            ),
        ),
    )

    reparsed = parse_ArtworkDB(write_ArtworkDB(edited))
    reparsed_image = reparsed.children[0].children[0].child_as(0, MhiiHeader)

    assert reparsed_image.header.image_id == 65
    assert reparsed_image.header.db_track_id_ref == 0x0102030405060708


def test_writer_reencodes_an_edited_artworkdb_string_and_lengths() -> None:
    album = _photo_album(7, 64, "Road Trip")
    album_list_bytes = bytearray(92)
    struct.pack_into("<4sII", album_list_bytes, 0, b"mhla", 92, 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.PHOTO_ALBUM_LIST,
            bytes(album_list_bytes) + album,
        )
    )
    database = parse_ArtworkDB(original)
    album_selection = database.find_chunks(MhbaHeader)[0]
    title_selection = album_selection.find_chunks(MhodHeader)[0]
    edited_title = title_selection.chunk.edit_payload(
        MhodStringPayload,
        lambda payload: replace(payload, value="Weekend"),
    )
    edited = database.replace_chunk(title_selection, edited_title)

    serialized = write_ArtworkDB(edited)
    reparsed = parse_ArtworkDB(serialized)
    reparsed_album = reparsed.children[0].children[0].child_as(0, MhbaHeader)
    reparsed_title = reparsed_album.child_as(0, MhodHeader)

    assert reparsed_title.payload_as(MhodStringPayload).value == "Weekend"
    assert len(serialized) == len(original) - 4


def test_writer_applies_an_edit_inside_an_mhod_container() -> None:
    image = _image_item()
    image_list_bytes = bytearray(92)
    struct.pack_into("<4sII", image_list_bytes, 0, b"mhli", 92, 1)
    database = parse_ArtworkDB(
        _artworkdb(
            _dataset(
                ArtworkDatasetType.IMAGE_LIST,
                bytes(image_list_bytes) + image,
            )
        )
    )
    dataset = database.children[0]
    image_list = dataset.children[0]
    parsed_image = image_list.child_as(0, MhiiHeader)
    thumbnail = parsed_image.child_as(0, MhodHeader)
    container = thumbnail.payload_as(MhodContainerPayload)
    edited_container = replace(
        container,
        child=replace(
            container.child,
            header=replace(container.child.header, ithmb_offset=8192),
        ),
    )
    edited_thumbnail = replace(thumbnail, payload=edited_container)
    edited_image = replace(parsed_image, children=(edited_thumbnail,))
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(image_list, children=(edited_image,)),),
            ),
        ),
    )

    reparsed = parse_ArtworkDB(write_ArtworkDB(edited))
    reparsed_image = reparsed.children[0].children[0].child_as(0, MhiiHeader)
    reparsed_container = reparsed_image.child_as(0, MhodHeader).payload_as(
        MhodContainerPayload
    )

    assert reparsed_container.child.header.ithmb_offset == 8192


def test_writer_recalculates_declared_child_counts() -> None:
    image = _image_item()
    image_list_bytes = bytearray(92)
    struct.pack_into("<4sII", image_list_bytes, 0, b"mhli", 92, 1)
    database = parse_ArtworkDB(
        _artworkdb(
            _dataset(
                ArtworkDatasetType.IMAGE_LIST,
                bytes(image_list_bytes) + image,
            )
        )
    )
    dataset = database.children[0]
    image_list = dataset.children[0]
    parsed_image = image_list.child_as(0, MhiiHeader)
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(
                    replace(
                        image_list,
                        children=(replace(parsed_image, children=()),),
                    ),
                ),
            ),
        ),
    )

    reparsed = parse_ArtworkDB(write_ArtworkDB(edited))
    reparsed_image = reparsed.children[0].children[0].child_as(0, MhiiHeader)

    assert reparsed_image.header.child_count == 0
    assert reparsed_image.children == ()


def test_writer_recalculates_multi_group_counts_after_a_tree_edit() -> None:
    album = _photo_album(7, 64, "Road Trip")
    album_list_bytes = bytearray(92)
    struct.pack_into("<4sII", album_list_bytes, 0, b"mhla", 92, 1)
    database = parse_ArtworkDB(
        _artworkdb(
            _dataset(
                ArtworkDatasetType.PHOTO_ALBUM_LIST,
                bytes(album_list_bytes) + album,
            )
        )
    )
    dataset = database.children[0]
    album_list = dataset.children[0]
    parsed_album = album_list.child_as(0, MhbaHeader)
    membership = parsed_album.child_as(1, MhiaHeader)
    edited_album = replace(
        parsed_album,
        children=(
            *parsed_album.children,
            replace(membership, header=replace(membership.header, image_id=65)),
        ),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(album_list, children=(edited_album,)),),
            ),
        ),
    )

    reparsed = parse_ArtworkDB(write_ArtworkDB(edited))
    reparsed_album = reparsed.children[0].children[0].child_as(0, MhbaHeader)

    assert reparsed_album.header.mhod_child_count == 1
    assert reparsed_album.header.image_child_count == 2
    assert reparsed_album.child_as(2, MhiaHeader).header.image_id == 65


def test_rejects_a_truncated_artworkdb() -> None:
    with pytest.raises(ValueError, match="extends past end of data"):
        parse_ArtworkDB(_empty_artworkdb()[:-1])


def test_unknown_photo_album_child_has_one_canonical_opaque_shape() -> None:
    unknown_data = b"future album metadata"
    unknown_child = (
        struct.pack(
            "<4sII",
            b"mhzz",
            12,
            12 + len(unknown_data),
        )
        + unknown_data
    )
    album = bytearray(148)
    struct.pack_into(
        "<4sIIII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(unknown_child),
        1,
        0,
    )
    album_list = bytearray(_empty_list(b"mhla"))
    struct.pack_into("<I", album_list, 8, 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.PHOTO_ALBUM_LIST,
            bytes(album_list) + bytes(album) + unknown_child,
        )
    )

    database = parse_ArtworkDB(original)

    assert write_ArtworkDB(database) == original

    dataset = database.children[0]
    parsed_album_list = dataset.children[0]
    parsed_album = parsed_album_list.child_as(0, MhbaHeader)
    unknown = parsed_album.children[0]
    edited_album = replace(
        parsed_album,
        children=(replace(unknown, prefix=MhodStringPrefix()),),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(parsed_album_list, children=(edited_album,)),),
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unknown Chunk cannot contain an MHOD prefix"):
        write_ArtworkDB(edited)


def test_writer_rejects_an_unknown_child_moved_across_declared_groups() -> None:
    title = _mhod_string(1, "Road Trip")
    unknown_data = b"future album metadata"
    unknown_child = (
        struct.pack("<4sII", b"mhzz", 12, 12 + len(unknown_data)) + unknown_data
    )
    member = bytearray(40)
    struct.pack_into("<4sII", member, 0, b"mhia", len(member), len(member))
    struct.pack_into("<I", member, 0x10, 64)
    children = title + unknown_child + bytes(member)
    album = bytearray(148)
    struct.pack_into(
        "<4sII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(children),
    )
    struct.pack_into("<II", album, 0x0C, 2, 1)
    album_list = bytearray(_empty_list(b"mhla"))
    struct.pack_into("<I", album_list, 8, 1)
    database = parse_ArtworkDB(
        _artworkdb(
            _dataset(
                ArtworkDatasetType.PHOTO_ALBUM_LIST,
                bytes(album_list) + bytes(album) + children,
            )
        )
    )
    dataset = database.children[0]
    parsed_album_list = dataset.children[0]
    parsed_album = parsed_album_list.child_as(0, MhbaHeader)
    edited_album = replace(
        parsed_album,
        children=(
            parsed_album.children[0],
            parsed_album.children[2],
            parsed_album.children[1],
        ),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(parsed_album_list, children=(edited_album,)),),
            ),
        ),
    )

    with pytest.raises(ValueError, match="declared child group 1"):
        write_ArtworkDB(edited)


def test_rejects_a_known_photo_album_child_in_the_wrong_declared_group() -> None:
    title = _mhod_string(1, "Road Trip")
    album = bytearray(148)
    struct.pack_into(
        "<4sIIII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(title),
        0,
        1,
    )
    album_list = bytearray(_empty_list(b"mhla"))
    struct.pack_into("<I", album_list, 8, 1)
    data = _artworkdb(
        _dataset(
            ArtworkDatasetType.PHOTO_ALBUM_LIST,
            bytes(album_list) + bytes(album) + title,
        )
    )

    with pytest.raises(ValueError, match="MHBA child group 2 must use b'mhia'"):
        parse_ArtworkDB(data)


def test_unknown_dataset_type_is_retained_as_opaque_unknown_data() -> None:
    opaque_data = b"future dataset payload\x00\xff"
    original = _artworkdb(_dataset(4, opaque_data))

    database = parse_ArtworkDB(original)
    dataset = database.child_as(0, MhsdHeader)

    assert dataset.header.dataset_type == 4
    assert dataset.children == ()
    assert dataset.payload_as(RawPayload).data == opaque_data
    assert write_ArtworkDB(database) == original


def test_rejects_known_dataset_with_the_wrong_list_marker() -> None:
    data = _artworkdb(_dataset(ArtworkDatasetType.IMAGE_LIST, _empty_list(b"mhla")))

    with pytest.raises(ValueError, match="dataset type 1 expects b'mhli'"):
        parse_ArtworkDB(data)


def test_rejects_known_list_with_the_wrong_known_child_marker() -> None:
    album = bytearray(148)
    struct.pack_into("<4sII", album, 0, b"mhba", len(album), len(album))
    image_list = bytearray(_empty_list(b"mhli"))
    struct.pack_into("<I", image_list, 8, 1)
    data = _artworkdb(
        _dataset(
            ArtworkDatasetType.IMAGE_LIST,
            bytes(image_list) + bytes(album),
        )
    )

    with pytest.raises(ValueError, match="b'mhli' child must use b'mhii'"):
        parse_ArtworkDB(data)


def test_rejects_a_header_shorter_than_the_generic_header() -> None:
    malformed = struct.pack("<4sII", b"mhfd", 0, 12)

    with pytest.raises(ValueError, match="header length 0 is smaller than 12"):
        parse_ArtworkDB(malformed)


def test_rejects_a_total_length_smaller_than_the_declared_header() -> None:
    malformed = bytearray(_empty_artworkdb())
    struct.pack_into("<I", malformed, 8, 0)

    with pytest.raises(ValueError, match="length is smaller than its header"):
        parse_ArtworkDB(malformed)


def test_root_level_trailing_unknown_data_is_preserved() -> None:
    original = _empty_artworkdb() + b"\xde\xadtrailing database data"

    database = parse_ArtworkDB(original)

    assert database.raw_source_suffix == b"\xde\xadtrailing database data"
    assert write_ArtworkDB(database) == original


def test_extended_string_mhod_header_is_parsed_from_declared_header_end() -> None:
    ordinary = _mhod_string(1, "Camera Roll")
    extended = bytearray(ordinary[:24]) + bytearray(b"\xde\xad\xbe\xef")
    extended.extend(ordinary[24:])
    struct.pack_into("<II", extended, 4, 28, len(extended))
    album = bytearray(148)
    struct.pack_into(
        "<4sII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(extended),
    )
    struct.pack_into("<I", album, 0x0C, 1)
    album_list = bytearray(_empty_list(b"mhla"))
    struct.pack_into("<I", album_list, 8, 1)
    original = _artworkdb(
        _dataset(
            ArtworkDatasetType.PHOTO_ALBUM_LIST,
            bytes(album_list) + bytes(album) + bytes(extended),
        )
    )

    database = parse_ArtworkDB(original)
    title = database.children[0].children[0].children[0].child_as(0, MhodHeader)

    assert title.payload_as(MhodStringPayload).value == "Camera Roll"
    assert title.raw_header[24:28] == b"\xde\xad\xbe\xef"
    assert write_ArtworkDB(database) == original


def test_string_edit_preserves_unknown_bytes_after_declared_padding() -> None:
    title_bytes = bytearray(_mhod_string(1, "Road Trip"))
    title_bytes.extend(b"\xde\xad")
    struct.pack_into("<I", title_bytes, 8, len(title_bytes))
    album = bytearray(148)
    struct.pack_into(
        "<4sII",
        album,
        0,
        b"mhba",
        len(album),
        len(album) + len(title_bytes),
    )
    struct.pack_into("<I", album, 0x0C, 1)
    album_list = bytearray(_empty_list(b"mhla"))
    struct.pack_into("<I", album_list, 8, 1)
    database = parse_ArtworkDB(
        _artworkdb(
            _dataset(
                ArtworkDatasetType.PHOTO_ALBUM_LIST,
                bytes(album_list) + bytes(album) + bytes(title_bytes),
            )
        )
    )
    dataset = database.children[0]
    parsed_album_list = dataset.children[0]
    parsed_album = parsed_album_list.child_as(0, MhbaHeader)
    title = parsed_album.child_as(0, MhodHeader)
    edited_title = replace(
        title,
        payload=replace(title.payload_as(MhodStringPayload), value="Weekend"),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(
                    replace(
                        parsed_album_list,
                        children=(replace(parsed_album, children=(edited_title,)),),
                    ),
                ),
            ),
        ),
    )

    reparsed = parse_ArtworkDB(write_ArtworkDB(edited))
    reparsed_title = (
        reparsed.children[0]
        .children[0]
        .children[0]
        .child_as(
            0,
            MhodHeader,
        )
    )

    assert reparsed_title.payload_as(MhodStringPayload).trailing_data == (
        b"\x00\xde\xad"
    )


def test_original_iopenpod_golden_fixture_round_trips_byte_exactly() -> None:
    fixture = _golden_fixture("original-empty.b64")

    assert write_ArtworkDB(parse_ArtworkDB(fixture)) == fixture


def test_unknown_data_golden_fixture_round_trips_byte_exactly() -> None:
    fixture = _golden_fixture("original-with-unknown-data.b64")

    database = parse_ArtworkDB(fixture)
    unknown = database.children[0].children[0].child_as(0, UnknownChunkHeader)

    assert unknown.payload_as(RawPayload).data == b"future image-list chunk"
    assert database.raw_source_suffix == b"ROOT-SUFFIX"
    assert write_ArtworkDB(database) == fixture


def test_new_artworkdb_matches_the_original_iopenpod_golden_fixture() -> None:
    fixture = _golden_fixture("original-empty.b64")

    assert write_ArtworkDB(new_ArtworkDB(next_mhii_id=64, unk_mhfd_0x10=2)) == fixture


def test_writer_constructs_new_typed_records_without_a_parsed_template() -> None:
    filename = new_string_mhod(ArtworkMhodType.FILE_NAME, ":F1060_1.ithmb")
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            ithmb_offset=4096,
            image_size=20000,
            image_height=100,
            image_width=200,
            image_size_2=20000,
        ),
        children=(filename,),
    )
    image_item = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(
            image_id=64,
            db_track_id_ref=0x0102030405060708,
            source_image_size=123456,
        ),
        children=(new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name),),
    )
    photo_album = new_artwork_chunk(
        MHBA_DEFINITION,
        MhbaHeader(album_id=7),
        children=(
            new_string_mhod(ArtworkMhodType.ALBUM_NAME, "Road Trip"),
            new_artwork_chunk(MHIA_DEFINITION, MhiaHeader(image_id=64)),
        ),
    )
    file_item = new_artwork_chunk(
        MHIF_DEFINITION,
        MhifHeader(format_id=1060, image_size=20000),
    )

    reparsed = parse_ArtworkDB(
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                image_items=(image_item,),
                photo_albums=(photo_album,),
                file_items=(file_item,),
            )
        )
    )
    reparsed_image = reparsed.children[0].children[0].child_as(0, MhiiHeader)
    reparsed_album = reparsed.children[1].children[0].child_as(0, MhbaHeader)
    reparsed_file = reparsed.children[2].children[0].child_as(0, MhifHeader)

    assert reparsed.header.next_mhii_id == 65
    assert reparsed_image.header.image_id == 64
    assert (
        reparsed_album.child_as(0, MhodHeader).payload_as(MhodStringPayload).value
        == "Road Trip"
    )
    assert reparsed_album.child_as(1, MhiaHeader).header.image_id == 64
    assert reparsed_file.header.format_id == 1060
    assert reparsed_file.header.image_size == 20000


def test_writer_rejects_a_constructed_list_with_the_wrong_record_type() -> None:
    membership = new_artwork_chunk(
        MHIA_DEFINITION,
        MhiaHeader(image_id=64),
    )
    database = new_ArtworkDB(
        next_mhii_id=65,
        unk_mhfd_0x10=2,
        image_items=(membership,),
    )

    with pytest.raises(ValueError, match="b'mhli' child must use b'mhii'"):
        write_ArtworkDB(database)


def test_known_mhod_constructors_reject_incompatible_payload_shapes() -> None:
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(format_id=1060),
    )

    with pytest.raises(ValueError, match="does not support a string payload"):
        new_string_mhod(ArtworkMhodType.FULL_RES_IMAGE, "not a container")
    with pytest.raises(ValueError, match="does not support a container payload"):
        new_container_mhod(ArtworkMhodType.ALBUM_NAME, image_name)


def test_writer_rejects_constructed_photo_album_children_in_group_reverse() -> None:
    photo_album = new_artwork_chunk(
        MHBA_DEFINITION,
        MhbaHeader(album_id=7),
        children=(
            new_artwork_chunk(MHIA_DEFINITION, MhiaHeader(image_id=64)),
            new_string_mhod(ArtworkMhodType.ALBUM_NAME, "Road Trip"),
        ),
    )

    with pytest.raises(ValueError, match="b'mhba' child groups are out of order"):
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                photo_albums=(photo_album,),
            )
        )


def test_writer_rejects_a_container_whose_typed_child_marker_was_changed() -> None:
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(format_id=1060),
    )
    container = new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name)
    payload = container.payload_as(MhodContainerPayload)
    changed_child = replace(
        payload.child,
        generic_header=replace(payload.child.generic_header, header_marker=b"mhzz"),
    )
    changed_container = replace(
        container,
        payload=replace(payload, child=changed_child),
    )
    image_item = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(image_id=64),
        children=(changed_container,),
    )

    with pytest.raises(ValueError, match="container child must use b'mhni'"):
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                image_items=(image_item,),
            )
        )
