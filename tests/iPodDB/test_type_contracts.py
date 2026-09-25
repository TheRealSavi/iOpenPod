"""Static contracts that keep the public iPodDB surface editor-friendly."""

from __future__ import annotations

import struct
from dataclasses import replace
from typing import TYPE_CHECKING, assert_type

if TYPE_CHECKING:
    from collections.abc import Callable

from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_artwork_chunk
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import (
    DEFINITION as ARTWORK_ROOT_DEFINITION,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.database_definition import (
    DATABASE_DEFINITION as ARTWORK_DATABASE_DEFINITION,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import (
    DEFINITION as ITUNES_ROOT_DEFINITION,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.database_definition import (
    DATABASE_DEFINITION as ITUNES_DATABASE_DEFINITION,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.PhotosDB.builder.build_PhotosDB import new_photos_chunk
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import (
    DEFINITION as PHOTOS_ROOT_DEFINITION,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader as PhotosMhfdHeader
from iPodDB.PhotosDB.shared.database_definition import (
    DATABASE_DEFINITION as PHOTOS_DATABASE_DEFINITION,
)
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.shared.chunk import ChunkSelection, DatabaseDocument, ParsedChunk
from iPodDB.shared.types import ChunkDefinition, DatabaseDefinition


def test_root_definitions_retain_their_exact_header_types() -> None:
    assert_type(
        ARTWORK_ROOT_DEFINITION,
        ChunkDefinition[MhfdHeader],
    )
    assert_type(
        ITUNES_ROOT_DEFINITION,
        ChunkDefinition[MhbdHeader],
    )
    assert_type(
        PHOTOS_ROOT_DEFINITION,
        ChunkDefinition[PhotosMhfdHeader],
    )
    assert_type(
        ARTWORK_DATABASE_DEFINITION,
        DatabaseDefinition[MhfdHeader],
    )
    assert_type(
        ITUNES_DATABASE_DEFINITION,
        DatabaseDefinition[MhbdHeader],
    )
    assert_type(
        PHOTOS_DATABASE_DEFINITION,
        DatabaseDefinition[PhotosMhfdHeader],
    )


def test_chunk_construction_preserves_the_definition_header_type() -> None:
    artwork_chunk = new_artwork_chunk(ARTWORK_ROOT_DEFINITION, MhfdHeader())
    itunes_chunk = new_itunes_chunk(ITUNES_ROOT_DEFINITION, MhbdHeader())
    photos_chunk = new_photos_chunk(PHOTOS_ROOT_DEFINITION, PhotosMhfdHeader())

    assert_type(artwork_chunk, ParsedChunk[MhfdHeader])
    assert_type(itunes_chunk, ParsedChunk[MhbdHeader])
    assert_type(photos_chunk, ParsedChunk[PhotosMhfdHeader])
    assert isinstance(artwork_chunk.header, MhfdHeader)
    assert isinstance(itunes_chunk.header, MhbdHeader)
    assert isinstance(photos_chunk.header, PhotosMhfdHeader)


def test_database_entry_points_have_symmetric_typed_interfaces() -> None:
    artwork_parser: Callable[
        [bytes | bytearray],
        DatabaseDocument[MhfdHeader],
    ] = parse_ArtworkDB
    artwork_writer: Callable[[DatabaseDocument[MhfdHeader]], bytes] = write_ArtworkDB
    photos_parser: Callable[
        [bytes | bytearray],
        DatabaseDocument[PhotosMhfdHeader],
    ] = parse_PhotosDB
    photos_writer: Callable[[DatabaseDocument[PhotosMhfdHeader]], bytes] = (
        write_PhotosDB
    )
    itunes_parser: Callable[
        [bytes | bytearray],
        DatabaseDocument[MhbdHeader],
    ] = parse_iTunesDB
    itunes_writer: Callable[[DatabaseDocument[MhbdHeader]], bytes] = write_iTunesDB

    assert callable(artwork_parser)
    assert callable(artwork_writer)
    assert callable(photos_parser)
    assert callable(photos_writer)
    assert callable(itunes_parser)
    assert callable(itunes_writer)


def test_tree_editing_preserves_root_and_selected_header_types() -> None:
    raw_database = bytearray(ITUNES_ROOT_DEFINITION.default_header_size)
    struct.pack_into(
        "<4sII",
        raw_database,
        0,
        ITUNES_ROOT_DEFINITION.marker,
        len(raw_database),
        len(raw_database),
    )
    database = parse_iTunesDB(raw_database)

    root_selection = database.find_chunks(MhbdHeader)[0]
    track_selections = database.find_chunks(MhitHeader)
    edited_root = root_selection.chunk.edit_header(
        lambda header: replace(header, db_id=42)
    )
    edited_database = database.replace_chunk(root_selection, edited_root)

    assert_type(root_selection, ChunkSelection[MhbdHeader, MhbdHeader])
    assert_type(
        track_selections,
        tuple[ChunkSelection[MhbdHeader, MhitHeader], ...],
    )
    assert_type(edited_database, DatabaseDocument[MhbdHeader])
    assert edited_database.header.db_id == 42
