import base64
from pathlib import Path
from typing import assert_type

import pytest

from iPodDB.shared.chunk import ChunkHeader, ParsedChunk
from iPodDB.shared.errors import UnexpectedHeaderMarkerError
from iPodDB.tools.chunk_browser import (
    BrowsableDatabase,
    DatabaseFamily,
    parse_browsable_database,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"


def _golden_fixture(database_family: str) -> bytes:
    encoded = (FIXTURE_DIR / database_family / "original-empty.b64").read_text(
        encoding="ascii"
    )
    return base64.b64decode("".join(encoded.splitlines()), validate=True)


@pytest.mark.parametrize(
    ("fixture_directory", "expected_family", "expected_root_marker"),
    (
        ("iTunesDB", DatabaseFamily.ITUNES_DB, b"mhbd"),
        ("ArtworkDB", DatabaseFamily.ARTWORK_DB, b"mhfd"),
    ),
)
def test_chunk_browser_dispatches_each_database_family_by_its_root_marker(
    fixture_directory: str,
    expected_family: DatabaseFamily,
    expected_root_marker: bytes,
) -> None:
    database = parse_browsable_database(_golden_fixture(fixture_directory))

    assert_type(database, BrowsableDatabase)
    assert_type(database.document, ParsedChunk[ChunkHeader])
    assert database.family is expected_family
    assert database.document.generic_header.header_marker == expected_root_marker


def test_chunk_browser_rejects_an_unknown_database_root() -> None:
    with pytest.raises(
        UnexpectedHeaderMarkerError,
        match="requires an iTunesDB or ArtworkDB root Header Marker",
    ):
        parse_browsable_database(b"nope")
