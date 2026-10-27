"""Playlist metadata must not rewrite the retained MHYP +0x28 behavior word."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_playlist_datasets import rows
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, Playlist


def retained_source(value: int, *, description: str = "") -> IPodLibrary:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    if description:
        for selection in document.find_chunks(MhypHeader):
            if not selection.chunk.header.master_flag:
                document = document.replace_chunk(
                    selection,
                    replace(
                        selection.chunk,
                        children=(
                            new_string_mhod(MhodType.ALBUM, description),
                            *selection.chunk.children,
                        ),
                    ),
                )
    data = bytearray(write_iTunesDB(document))
    document = parse_iTunesDB(bytes(data))
    for kind, raw in ((2, value), (3, value ^ 0x8000)):
        playlist = rows(document, kind)[1].chunk
        # Independent byte fixture: no field-name or writer-derived expectation.
        struct.pack_into("<H", data, playlist.offset + 0x28, raw)
    return IPodLibrary(bytes(data))


@pytest.mark.parametrize("value", [0, 1, 2, 3, 0xFFFF])
@pytest.mark.parametrize("edit", ["title", "add_description", "remove_description"])
def test_metadata_edits_preserve_each_counterparts_raw_behavior_word(
    value: int, edit: str
) -> None:
    source = retained_source(
        value,
        description="Retained description" if edit == "remove_description" else "",
    )
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    playlist = source.snapshot.playlists[0]
    changed = (
        replace(playlist, name="Renamed")
        if edit == "title"
        else replace(
            playlist,
            description="Added description" if edit == "add_description" else "",
        )
    )
    desired = replace(source.snapshot, playlists=(changed,))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    checked = parse_iTunesDB(data)
    for kind, expected in ((2, value), (3, value ^ 0x8000)):
        native = rows(checked, kind)[1].chunk
        assert struct.unpack_from("<H", data, native.offset + 0x28)[0] == expected
        metadata_count = sum(isinstance(c.header, MhodHeader) for c in native.children)
        assert struct.unpack_from("<I", data, native.offset + 0x0C)[0] == metadata_count
    assert result.prepared.snapshot.playlists[0] == changed
    assert source.serialize().itunes == original


@pytest.mark.parametrize("version", [0x13, 0x19, 0x75])
@pytest.mark.parametrize("description", ["", "A second metadata string"])
def test_new_playlist_behavior_default_is_independent_of_metadata_count(
    version: int, description: str
) -> None:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    document = replace(document, header=replace(document.header, version=version))
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", description=description),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    checked = parse_iTunesDB(data)
    identity = result.prepared.snapshot.playlists[-1].playlist_id
    for kind in (2, 3):
        native = next(
            s.chunk
            for s in rows(checked, kind)
            if s.chunk.header.playlist_id == identity
        )
        assert struct.unpack_from("<H", data, native.offset + 0x28)[0] == 1
        # Title plus display preferences, and optionally description.
        assert struct.unpack_from("<I", data, native.offset + 0x0C)[0] == (
            3 if description else 2
        )


@pytest.mark.parametrize("header_size", [0x28, 0x29, 0x2A, 0x30])
def test_description_edit_preserves_short_header_and_partial_behavior_bytes(
    header_size: int,
) -> None:
    original = retained_source(0xFEDC).serialize().itunes
    document = parse_iTunesDB(original)
    data = bytearray(original)
    # Work backwards so the original offsets of earlier datasets remain valid.
    datasets = sorted(
        (
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type in (2, 3)
        ),
        key=lambda s: s.chunk.offset,
        reverse=True,
    )
    for dataset in datasets:
        playlist = dataset.find_chunks(MhypHeader)[1].chunk
        delta = playlist.generic_header.header_length - header_size
        del data[
            playlist.offset + header_size : playlist.offset
            + playlist.generic_header.header_length
        ]
        struct.pack_into("<I", data, playlist.offset + 4, header_size)
        struct.pack_into(
            "<I",
            data,
            playlist.offset + 8,
            playlist.generic_header.length_or_child_count - delta,
        )
        struct.pack_into(
            "<I",
            data,
            dataset.chunk.offset + 8,
            dataset.chunk.generic_header.length_or_child_count - delta,
        )
    struct.pack_into("<I", data, 8, len(data))
    source = IPodLibrary(bytes(data))
    assert source.serialize().itunes == bytes(data)
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == bytes(data)
    before = parse_iTunesDB(bytes(data))
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], description="New text"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        prior = rows(before, kind)[1].chunk
        after = rows(checked, kind)[1].chunk
        assert after.generic_header.header_length == header_size
        assert after.raw_header[0x28:0x2A] == prior.raw_header[0x28:0x2A]
