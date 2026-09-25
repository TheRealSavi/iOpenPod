"""Typed error modes exposed by both public database-family seams."""

import struct
from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_artwork_chunk
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import (
    DEFINITION as ARTWORK_ROOT_DEFINITION,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.PhotosDB.builder.build_PhotosDB import new_photos_chunk
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import (
    DEFINITION as PHOTOS_ROOT_DEFINITION,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader as PhotosMhfdHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.shared.chunk import GenericHeader, ParsedChunk
from iPodDB.shared.errors import (
    TruncatedChunkError,
    UnexpectedHeaderMarkerError,
    iPodDBWriteError,
)


def test_public_parsers_report_truncation_with_the_shared_error_type() -> None:
    for parser in (parse_ArtworkDB, parse_PhotosDB, parse_iTunesDB):
        with pytest.raises(TruncatedChunkError):
            parser(b"")


def test_public_parsers_report_the_wrong_root_marker_explicitly() -> None:
    wrong_root = struct.pack("<4sII", b"nope", 12, 12)

    for parser in (parse_ArtworkDB, parse_PhotosDB, parse_iTunesDB):
        with pytest.raises(UnexpectedHeaderMarkerError):
            parser(wrong_root)


def test_public_writers_report_the_wrong_root_marker_explicitly() -> None:
    artwork = new_artwork_chunk(ARTWORK_ROOT_DEFINITION, MhfdHeader())
    wrong_artwork = replace(
        artwork,
        generic_header=replace(artwork.generic_header, header_marker=b"mhbd"),
    )
    wrong_itunes = ParsedChunk[MhbdHeader](
        offset=0,
        generic_header=GenericHeader(
            header_marker=b"mhfd",
            header_length=0,
            length_or_child_count=0,
        ),
        header=MhbdHeader(),
        children=(),
        prefix=None,
        payload=None,
    )
    photos = new_photos_chunk(PHOTOS_ROOT_DEFINITION, PhotosMhfdHeader())
    wrong_photos = replace(
        photos,
        generic_header=replace(photos.generic_header, header_marker=b"mhbd"),
    )

    with pytest.raises(iPodDBWriteError, match="database root"):
        write_ArtworkDB(wrong_artwork)
    with pytest.raises(iPodDBWriteError, match="database root"):
        write_iTunesDB(wrong_itunes)
    with pytest.raises(iPodDBWriteError, match="database root"):
        write_PhotosDB(wrong_photos)


def test_chunk_selection_rejects_stale_and_marker_changing_replacements() -> None:
    database = new_artwork_chunk(ARTWORK_ROOT_DEFINITION, MhfdHeader())
    selection = database.find_chunks(MhfdHeader)[0]
    edited_root = selection.chunk.edit_header(
        lambda header: replace(header, next_mhii_id=64)
    )
    edited_database = database.replace_chunk(selection, edited_root)

    with pytest.raises(ValueError, match="selection is stale"):
        edited_database.replace_chunk(selection, edited_root)

    wrong_marker = replace(
        selection.chunk,
        generic_header=replace(
            selection.chunk.generic_header,
            header_marker=b"mhbd",
        ),
    )
    with pytest.raises(ValueError, match="retain Header Marker"):
        database.replace_chunk(selection, wrong_marker)
