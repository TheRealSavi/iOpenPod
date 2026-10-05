"""Bounded extensions are retained on reads and edits, with log-only diagnostics."""

import logging
import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import artwork_database as _artworkdb
from tests.iPodDB.binary_fixtures import dataset as _dataset
from tests.iPodDB.binary_fixtures import itunes_database as _database
from tests.iPodDB.binary_fixtures import length_chunk as _length_chunk
from tests.iPodDB.binary_fixtures import list_chunk as _list_chunk
from tests.iPodDB.binary_fixtures import mhod as _mhod
from tests.iPodDB.binary_fixtures import parse_mhod as _parse_mhod
from tests.iPodDB.binary_fixtures import photo_album as _photo_album
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg, stats

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.library.writing import WriteTarget
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.shared.chunk import UnknownMhodPayload
from iPodDB.shared.errors import iPodDBWriteError
from iPodDB.sidecars import (
    parse_itunes_stats,
    parse_otg_playlist,
    parse_play_counts,
    remap_playback_sidecar,
)


@pytest.mark.parametrize("suffix", (b"\0", b"future extension"))
def test_playlist_position_extension_is_retained(suffix: bytes) -> None:
    body = struct.pack("<I", 7) + bytes(16) + suffix
    entry = _length_chunk(b"mhip", 76, _mhod(100, body), fields=struct.pack("<I", 1))
    playlist = _length_chunk(b"mhyp", 108, entry, fields=struct.pack("<II", 0, 1))
    original = _database(_dataset(3, _list_chunk(b"mhlp", playlist)))
    document = parse_iTunesDB(original)
    assert write_iTunesDB(document) == original
    position = document.find_chunks(MhodHeader)[0]
    assert (
        position.chunk.payload_as(MhodPlaylistPositionPayload).trailing_data == suffix
    )
    edited = document.replace_chunk(
        position,
        position.chunk.edit_prefix(
            MhodPlaylistPositionPrefix, lambda prefix: replace(prefix, position=9)
        ),
    )
    expected = bytearray(original)
    struct.pack_into("<I", expected, position.chunk.offset + 24, 9)
    assert write_iTunesDB(edited) == expected


@pytest.mark.parametrize(
    "inner,outer", ((b"inner", b""), (b"", b"outer"), (b"I", b"O"))
)
def test_chapter_extensions_survive_a_known_field_edit(
    inner: bytes, outer: bytes
) -> None:
    body = (
        bytes(12)
        + struct.pack(">I4sIII", 20 + len(inner), b"sean", 0, 0, 0)
        + inner
        + outer
    )
    chunk = _parse_mhod(17, body)
    encoded, _ = encode_mhod_body(chunk, MhodPayloadKind.CHAPTER_DATA)
    assert encoded == body
    edited = chunk.edit_payload(
        MhodChapterDataPayload,
        lambda value: replace(value, sean=replace(value.sean, unk_0x08=123)),
    )
    encoded, _ = encode_mhod_body(edited, MhodPayloadKind.CHAPTER_DATA)
    expected = bytearray(body)
    struct.pack_into(">I", expected, 20, 123)
    assert encoded == expected
    assert _parse_mhod(17, encoded).payload == edited.payload


@pytest.mark.parametrize("endian", ("<", ">"))
def test_play_counts_suffix_survives_remapping(endian: str) -> None:
    original = counts(((3, 0, 0), (5, 0, 0)), endian=endian, width=12)
    suffix = b"\0opaque suffix"
    parsed = parse_play_counts(original + suffix)
    assert tuple(row.play_count for row in parsed.entries) == (3, 5)
    assert parsed.serialize() == original + suffix
    edited = remap_playback_sidecar(original + suffix, (10, 20), (20,))
    assert edited.endswith(suffix)
    assert parse_play_counts(edited).entries[0].play_count == 5


def test_otg_suffix_survives_remapping() -> None:
    original = otg((1, 0)) + b"future"
    assert parse_otg_playlist(original).serialize() == original
    edited = remap_playback_sidecar(original, (10, 20), (20,))
    assert parse_otg_playlist(edited).positions == (0,)
    assert edited.endswith(b"future")


@pytest.mark.parametrize("word", (3, 4))
def test_stats_suffix_is_retained(word: int) -> None:
    original = stats(word) + b"future"
    parsed = parse_itunes_stats(original)
    assert tuple(row.play_count for row in parsed.entries) == (3, 5)
    assert parsed.serialize() == original


@pytest.mark.parametrize(
    "inside,outside", ((b"inside", b""), (b"", b"outside"), (b"I", b"O"))
)
def test_cdb_extensions_survive_recompression(inside: bytes, outside: bytes) -> None:
    physical = bytearray(compress_iTunesCDB(_database()))
    physical.extend(inside)
    physical[8:12] = len(physical).to_bytes(4, "little")
    physical.extend(outside)
    captured = bytes(physical)
    framing = decompress_iTunesCDB(captured)
    assert IPodLibrary.parse(captured).serialize().itunes == captured
    assert compress_iTunesCDB(framing.logical_bytes, framing=framing) == captured
    logical = bytearray(framing.logical_bytes)
    logical[0x10:0x14] = (117).to_bytes(4, "little")
    edited = compress_iTunesCDB(logical, framing=framing)
    declared = int.from_bytes(edited[8:12], "little")
    assert edited[declared:] == outside
    if inside:
        assert edited[:declared].endswith(inside)
    assert decompress_iTunesCDB(edited).logical_bytes == logical


def test_unknown_chunks_log_bounded_location_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = b"private track title must not appear in logs"
    chunks = tuple(_length_chunk(b"mhzz", 12, secret) for _ in range(100))
    original = _database(_dataset(1, _list_chunk(b"mhlt", *chunks))) + b"suffix"
    with caplog.at_level(logging.WARNING, logger="iPodDB"):
        parsed = parse_iTunesDB(original)
    assert write_iTunesDB(parsed) == original
    assert 0 < len(caplog.records) <= 2
    assert "Unknown Data" in caplog.text
    assert "mhzz" in caplog.text
    assert "database suffix" in caplog.text
    assert "0x" in caplog.text
    assert "101" in caplog.text
    assert secret.decode() not in caplog.text


def test_unknown_dataset_child_remains_opaque_and_writable() -> None:
    original = _database(_dataset(1, _length_chunk(b"mhzz", 12, b"future list")))
    assert write_iTunesDB(parse_iTunesDB(original)) == original
    assert IPodLibrary.parse(original).snapshot.tracks == ()


@pytest.mark.parametrize(
    "kind,body",
    (
        (1, struct.pack("<IIII", 99, 3, 0, 0) + b"odd"),
        (17, bytes(12) + struct.pack(">I4sIII", 20, b"NEXT", 0, 0, 0)),
        (51, b"NEXT" + bytes(132)),
    ),
)
def test_unknown_mhod_layout_survives_unrelated_edit(kind: int, body: bytes) -> None:
    track = _length_chunk(b"mhit", 156, _mhod(kind, body), fields=struct.pack("<I", 1))
    original = _database(_dataset(1, _list_chunk(b"mhlt", track)))
    source = IPodLibrary.parse(original)
    assert len(source.snapshot.tracks) == 1
    assert source.serialize().itunes == original
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    edited = document.replace_chunk(
        selected, selected.chunk.edit_header(lambda header: replace(header, rating=80))
    )
    encoded = write_iTunesDB(edited)
    expected = bytearray(original)
    expected[selected.chunk.offset + 0x1F] = 80
    assert encoded == expected
    payload = parse_iTunesDB(encoded).find_chunks(MhodHeader)[0].chunk.payload
    assert isinstance(payload, UnknownMhodPayload)
    assert payload.data == body


def test_unknown_mhod_cannot_be_silently_retyped_or_rewritten() -> None:
    body = b"NEXT" + bytes(132)
    track = _length_chunk(b"mhit", 156, _mhod(51, body), fields=struct.pack("<I", 1))
    original = _database(_dataset(1, _list_chunk(b"mhlt", track)))
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhodHeader)[0]
    for modified in (
        selected.chunk.edit_header(lambda header: replace(header, mhod_type=50)),
        selected.chunk.edit_payload(
            UnknownMhodPayload, lambda payload: replace(payload, data=b"changed")
        ),
    ):
        with pytest.raises(iPodDBWriteError, match="must retain"):
            write_iTunesDB(document.replace_chunk(selected, modified))


@pytest.mark.parametrize("photos", (False, True))
def test_image_database_unknown_encoding_roundtrips(photos: bool) -> None:
    album = bytearray(_photo_album(1, 1, "odd"))
    # mhba header (148), mhod header (24), then length (4), encoding byte.
    album[148 + 24 + 4] = 99
    data = _artworkdb(_dataset(2, _list_chunk(b"mhla", bytes(album))))
    if photos:
        document = parse_PhotosDB(data)
        assert write_PhotosDB(document) == data
    else:
        artwork = parse_ArtworkDB(data)
        assert write_ArtworkDB(artwork) == data


@pytest.mark.parametrize("photos", (False, True))
def test_image_container_unknown_child_roundtrips(photos: bool) -> None:
    unknown = _length_chunk(b"mhzz", 12, b"future image reference")
    item = _length_chunk(b"mhii", 152, _mhod(2, unknown), fields=struct.pack("<I", 1))
    data = _artworkdb(_dataset(1, _list_chunk(b"mhli", item)))
    if photos:
        assert write_PhotosDB(parse_PhotosDB(data)) == data
    else:
        assert write_ArtworkDB(parse_ArtworkDB(data)) == data


def test_cdb_public_preparation_preserves_physical_extensions() -> None:
    physical = bytearray(compress_iTunesCDB(library().serialize().itunes))
    physical.extend(b"stream-tail")
    physical[8:12] = len(physical).to_bytes(4, "little")
    physical.extend(b"file-tail")
    source = IPodLibrary.parse(bytes(physical))
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Edited"),),
    )
    draft = source.begin_draft(desired)
    result = source.prepare(
        source.analyze(draft, WriteTarget(compressed_database=True))
    )
    assert result.prepared is not None, result.issues
    framing = decompress_iTunesCDB(result.prepared.itunes)
    assert framing.stream_trailing_data == b"stream-tail"
    assert framing.file_trailing_data == b"file-tail"
    assert (
        IPodLibrary.parse(result.prepared.itunes).snapshot.playlists[0].name == "Edited"
    )
    conversion = source.prepare(source.analyze(draft, WriteTarget()))
    assert conversion.prepared is None


def test_diagnostics_are_scoped_to_each_read(caplog: pytest.LogCaptureFixture) -> None:
    original = _database(_dataset(99, b"unknown"))
    for _ in range(2):
        parse_iTunesDB(original)
    assert len(caplog.records) == 2
    assert caplog.records[0].getMessage() == caplog.records[1].getMessage()
    caplog.clear()
    parse_iTunesDB(_database())
    assert not caplog.records


@pytest.mark.parametrize(
    "kind,body",
    (
        (17, bytes(11)),
        (17, bytes(12) + struct.pack(">I4sIII", 20, b"sean", 0, 1, 0)),
        (50, bytes(13)),
        (1, struct.pack("<IIII", 99, 100, 0, 0) + b"short"),
    ),
)
def test_unknown_layout_fallback_does_not_hide_truncation(
    kind: int, body: bytes
) -> None:
    with pytest.raises(ValueError):
        _parse_mhod(kind, body)


def test_extended_mhod_header_stays_opaque() -> None:
    metadata = _length_chunk(b"mhod", 44, b"future", fields=struct.pack("<I", 1))
    track = _length_chunk(b"mhit", 156, metadata, fields=struct.pack("<I", 1))
    data = _database(_dataset(1, _list_chunk(b"mhlt", track)))
    document = parse_iTunesDB(data)
    assert isinstance(
        document.find_chunks(MhodHeader)[0].chunk.payload, UnknownMhodPayload
    )
    assert write_iTunesDB(document) == data


def test_cdb_extensions_do_not_bypass_decompression_bounds() -> None:
    data = bytearray(compress_iTunesCDB(_database(_dataset(99, bytes(1024)))))
    truncated = data[:-1]
    truncated[8:12] = len(truncated).to_bytes(4, "little")
    with pytest.raises(ValueError, match="incomplete"):
        decompress_iTunesCDB(truncated)
    data.extend(b"retained")
    data[8:12] = len(data).to_bytes(4, "little")
    with pytest.raises(ValueError, match="logical-byte limit"):
        decompress_iTunesCDB(data, max_logical_bytes=256)
