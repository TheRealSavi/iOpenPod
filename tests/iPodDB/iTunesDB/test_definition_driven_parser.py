import base64
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.shared.chunk import RawPayload, UnknownChunkHeader
from iPodDB.shared.types import OpaqueMhsdDatasetDefinition

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "iTunesDB"


def _golden_fixture(name: str) -> bytes:
    return base64.b64decode(
        "".join((FIXTURE_DIR / name).read_text(encoding="ascii").splitlines()),
        validate=True,
    )


def _length_chunk(
    marker: bytes,
    header_length: int,
    body: bytes = b"",
    *,
    fields: bytes = b"",
) -> bytes:
    header = bytearray(header_length)
    struct.pack_into(
        "<4sII", header, 0, marker, header_length, header_length + len(body)
    )
    header[12 : 12 + len(fields)] = fields
    return bytes(header) + body


def _list_chunk(marker: bytes, *children: bytes) -> bytes:
    header = bytearray(92)
    struct.pack_into("<4sII", header, 0, marker, len(header), len(children))
    return bytes(header) + b"".join(children)


def _dataset(dataset_type: int, child: bytes) -> bytes:
    return _length_chunk(
        b"mhsd",
        96,
        child,
        fields=struct.pack("<I", dataset_type),
    )


def _database(*datasets: bytes) -> bytes:
    fields = bytearray(12)
    struct.pack_into("<I", fields, 8, len(datasets))
    return _length_chunk(b"mhbd", 244, b"".join(datasets), fields=bytes(fields))


def _string_mhod(value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    body = struct.pack("<IIII", 1, len(encoded), 1, 0) + encoded
    return _length_chunk(
        b"mhod",
        24,
        body,
        fields=struct.pack("<III", 1, 0, 0),
    )


def test_itunesdb_rejects_a_known_dataset_with_the_wrong_list_chunk() -> None:
    data = _database(_dataset(1, _list_chunk(b"mhlp")))

    with pytest.raises(ValueError, match=r"dataset type 1 expects b'mhlt'"):
        parse_iTunesDB(data)


def test_itunesdb_preserves_an_unknown_dataset_as_opaque_data() -> None:
    opaque_data = b"future dataset bytes"
    database = parse_iTunesDB(_database(_dataset(77, opaque_data)))

    assert database.children[0].payload_as(RawPayload).data == opaque_data


def test_itunesdb_registers_reserved_dataset_7_as_explicitly_opaque() -> None:
    definition = DATABASE_DEFINITION.dataset_definition(7)

    assert isinstance(definition, OpaqueMhsdDatasetDefinition)
    assert definition.dataset_type == 7


def test_itunesdb_preserves_an_unknown_chunk_inside_a_known_container() -> None:
    unknown_body = b"future track child"
    unknown = _length_chunk(b"mhzz", 12, unknown_body)
    track = _length_chunk(
        b"mhit",
        0x9C,
        unknown,
        fields=struct.pack("<I", 1),
    )
    database = parse_iTunesDB(_database(_dataset(1, _list_chunk(b"mhlt", track))))

    parsed_unknown = (
        database.children[0]
        .children[0]
        .children[0]
        .child_as(
            0,
            UnknownChunkHeader,
        )
    )
    assert parsed_unknown.payload_as(RawPayload).data == unknown_body


def test_itunesdb_preserves_data_after_the_declared_root_extent() -> None:
    source_suffix = b"ROOT-SUFFIX"

    database = parse_iTunesDB(_database() + source_suffix)

    assert database.raw_source_suffix == source_suffix


def test_itunesdb_unchanged_round_trip_preserves_every_source_byte() -> None:
    unknown_body = b"future track child"
    unknown = _length_chunk(b"mhzz", 12, unknown_body)
    track = _length_chunk(
        b"mhit",
        0x9C,
        unknown,
        fields=struct.pack("<I", 1),
    )
    original = (
        _database(
            _dataset(1, _list_chunk(b"mhlt", track)),
            _dataset(77, b"future dataset bytes"),
        )
        + b"ROOT-SUFFIX"
    )

    assert write_iTunesDB(parse_iTunesDB(original)) == original


def test_itunesdb_unchanged_round_trip_preserves_float_bit_patterns() -> None:
    track_fields = bytearray(0x9C - 12)
    struct.pack_into("<I", track_fields, 0x88 - 12, 0x7F800001)
    track = _length_chunk(b"mhit", 0x9C, fields=bytes(track_fields))
    original = _database(_dataset(1, _list_chunk(b"mhlt", track)))

    assert write_iTunesDB(parse_iTunesDB(original)) == original


def test_original_iopenpod_itunesdb_round_trips_byte_for_byte() -> None:
    original = _golden_fixture("original-empty.b64")

    assert write_iTunesDB(parse_iTunesDB(original)) == original


def test_itunesdb_writer_repairs_root_count_and_extent_after_a_tree_edit() -> None:
    database = parse_iTunesDB(
        _database(
            _dataset(1, _list_chunk(b"mhlt")),
            _dataset(77, b"future dataset bytes"),
        )
    )
    edited = replace(database, children=database.children[:1])

    serialized = write_iTunesDB(edited)
    reparsed = parse_iTunesDB(serialized)

    assert reparsed.header.child_count == 1
    assert len(reparsed.children) == 1
    assert reparsed.generic_header.length_or_child_count == len(serialized)


def test_itunesdb_writer_rejects_a_payload_on_a_children_chunk() -> None:
    database = parse_iTunesDB(_database())
    edited = replace(database, payload=RawPayload(b"must not be discarded"))

    with pytest.raises(ValueError, match="children Chunk cannot contain a payload"):
        write_iTunesDB(edited)


def test_itunesdb_writer_rejects_an_edit_beyond_a_retained_short_header() -> None:
    database = parse_iTunesDB(_length_chunk(b"mhbd", 24))
    edited = replace(database, header=replace(database.header, db_id=123))

    with pytest.raises(ValueError, match=r"MhbdHeader.db_id.*24-byte header"):
        write_iTunesDB(edited)


def test_mhbd_adjacent_fields_parse_and_write_without_overlap() -> None:
    raw_database = bytearray(_database())
    struct.pack_into("<I", raw_database, 0x2C, 0x10203040)
    struct.pack_into("<H", raw_database, 0x30, 0x5060)
    raw_database[0x32:0x46] = bytes(range(20))

    database = parse_iTunesDB(raw_database)

    assert database.header.unk_mhbd_0x2c == 0x10203040
    assert database.header.hashing_scheme == 0x5060
    assert database.header.unk0x32 == bytes(range(20))

    edited = replace(
        database,
        header=replace(
            database.header,
            unk_mhbd_0x2c=0xA1B2C3D4,
            hashing_scheme=0xE5F6,
            unk0x32=bytes(reversed(range(20))),
        ),
    )
    serialized = write_iTunesDB(edited)

    assert serialized[0x2C:0x30] == bytes.fromhex("d4c3b2a1")
    assert serialized[0x30:0x32] == bytes.fromhex("f6e5")
    assert serialized[0x32:0x46] == bytes(reversed(range(20)))


def test_itunesdb_writer_rejects_contextual_mhod_moved_to_the_wrong_parent() -> None:
    playlist_preferences = _length_chunk(
        b"mhod",
        24,
        bytes(624),
        fields=struct.pack("<III", 100, 0, 0),
    )
    playlist_position = _length_chunk(
        b"mhod",
        24,
        struct.pack("<I", 42) + bytes(16),
        fields=struct.pack("<III", 100, 0, 0),
    )
    playlist_item = _length_chunk(
        b"mhip",
        76,
        playlist_position,
        fields=struct.pack("<I", 1),
    )
    playlist = _length_chunk(
        b"mhyp",
        184,
        playlist_preferences + playlist_item,
        fields=struct.pack("<II", 1, 1),
    )
    database = parse_iTunesDB(_database(_dataset(2, _list_chunk(b"mhlp", playlist))))
    dataset = database.children[0]
    playlist_list = dataset.children[0]
    parsed_playlist = playlist_list.child_as(0, MhypHeader)
    parsed_preferences = parsed_playlist.child_as(0, MhodHeader)
    parsed_item = parsed_playlist.child_as(1, MhipHeader)
    edited_item = replace(parsed_item, children=(parsed_preferences,))
    edited_playlist = replace(
        parsed_playlist,
        children=(parsed_preferences, edited_item),
    )
    edited = replace(
        database,
        children=(
            replace(
                dataset,
                children=(replace(playlist_list, children=(edited_playlist,)),),
            ),
        ),
    )

    with pytest.raises(ValueError, match="MHOD type 100 requires"):
        write_iTunesDB(edited)


def test_itunesdb_writer_uses_the_shared_path_for_typed_mhod_data() -> None:
    title = _string_mhod("Miles")
    track = _length_chunk(
        b"mhit",
        0x9C,
        title,
        fields=struct.pack("<I", 1),
    )
    original = _database(_dataset(1, _list_chunk(b"mhlt", track)))

    database = parse_iTunesDB(original)
    parsed_title = (
        database.children[0].children[0].child_as(0, MhitHeader).child_as(0, MhodHeader)
    )

    assert parsed_title.payload_as(MhodStringPayload).value == "Miles"
    assert write_iTunesDB(database) == original


def test_consumer_can_replace_a_typed_itunesdb_string_and_write_it() -> None:
    title = _string_mhod("Miles")
    track = _length_chunk(
        b"mhit",
        0x9C,
        title,
        fields=struct.pack("<I", 1),
    )
    database = parse_iTunesDB(_database(_dataset(1, _list_chunk(b"mhlt", track))))
    track_selection = database.find_chunks(MhitHeader)[0]
    title_selection = track_selection.find_chunks(MhodHeader)[0]
    edited_title = title_selection.chunk.edit_payload(
        MhodStringPayload,
        lambda payload: replace(payload, value="Coltrane"),
    )
    edited = database.replace_chunk(title_selection, edited_title)

    serialized = write_iTunesDB(edited)
    reparsed = parse_iTunesDB(serialized)
    reparsed_title = (
        reparsed.find_chunks(MhitHeader)[0].find_chunks(MhodHeader)[0].chunk
    )

    assert reparsed_title.payload_as(MhodStringPayload).value == "Coltrane"
    assert len(serialized) == len(write_iTunesDB(database)) + 6


def test_consumer_can_append_a_new_typed_itunesdb_string_and_write_it() -> None:
    track = _length_chunk(
        b"mhit",
        0x9C,
        fields=struct.pack("<I", 0),
    )
    database = parse_iTunesDB(_database(_dataset(1, _list_chunk(b"mhlt", track))))
    track_selection = database.find_chunks(MhitHeader)[0]
    edited_track = track_selection.chunk.append_child(new_string_mhod(1, "Blue Train"))
    edited = database.replace_chunk(track_selection, edited_track)

    reparsed = parse_iTunesDB(write_iTunesDB(edited))
    reparsed_track = reparsed.find_chunks(MhitHeader)[0]
    title = reparsed_track.find_chunks(MhodHeader)[0].chunk

    assert reparsed_track.chunk.header.child_count == 1
    assert title.payload_as(MhodStringPayload).value == "Blue Train"
