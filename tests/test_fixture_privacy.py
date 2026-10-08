"""Keep stored fixtures free of personal data, including encoded database bytes."""

import base64
import json
import re
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import cast

import pytest

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk, chunk_as

FIXTURES = Path(__file__).parent / "fixtures"
EMAIL = re.compile(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}")
PERSONAL_PATH = re.compile(
    r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:Users|home)/"
)


def _embedded_bytes(value: object) -> Iterator[bytes]:
    if isinstance(value, dict):
        for child in cast("dict[object, object]", value).values():
            yield from _embedded_bytes(child)
    elif isinstance(value, list):
        for child in cast("list[object]", value):
            yield from _embedded_bytes(child)
    elif isinstance(value, str) and len(value) >= 64:
        if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
            yield bytes.fromhex(value)
        with suppress(ValueError):
            yield base64.b64decode(value, validate=True)


@pytest.mark.parametrize(
    "path",
    sorted(p for p in FIXTURES.rglob("*") if p.suffix in {".b64", ".json", ".plist"}),
    ids=lambda p: p.relative_to(FIXTURES).as_posix(),
)
def test_stored_fixtures_have_no_emails_or_personal_host_paths(path: Path) -> None:
    data = path.read_bytes()
    blobs = [base64.b64decode(data) if path.suffix == ".b64" else data]
    if path.suffix == ".json":
        blobs.extend(_embedded_bytes(json.loads(data)))
    for blob in blobs:
        texts = [blob.decode("utf-8", errors="ignore")]
        texts.extend(
            blob[offset:].decode(encoding, errors="ignore")
            for encoding in ("utf-16le", "utf-16be")
            for offset in (0, 1)
        )
        # Report the file, never the potentially private match itself.
        assert not any(EMAIL.search(text) for text in texts), path.name
        assert not any(PERSONAL_PATH.search(text) for text in texts), path.name


def _clean_chunk(chunk: ParsedChunk[ChunkHeader]) -> ParsedChunk[ChunkHeader]:
    marker = chunk.generic_header.header_marker
    allowed: dict[bytes, set[str]] = {
        b"mhbd": {"child_count"},
        b"mhsd": {"dataset_type"},
        b"mhlt": set(),
        b"mhit": {
            "child_count",
            "track_id",
            "db_track_id",
            "album_id",
            "length",
            "disc_number",
            "track_number",
            "compilation_flag",
        },
        b"mhlp": set(),
        b"mhyp": {"mhod_child_count", "mhip_child_count", "playlist_id", "master_flag"},
        b"mhip": {"track_id"},
        b"mhla": set(),
        b"mhia": {"child_count", "album_id", "sql_id", "album_track_db_id"},
        b"mhod": {"mhod_type"},
    }
    assert marker in allowed
    assert is_dataclass(chunk.header)
    defaults = type(chunk.header)()
    for field in fields(chunk.header):
        if field.name not in allowed[marker]:
            assert getattr(chunk.header, field.name) == getattr(defaults, field.name), (
                marker,
                field.name,
            )
    if isinstance(chunk.payload, MhodStringPayload):
        assert marker == b"mhod"
        assert isinstance(chunk.header, MhodHeader)
        kind = chunk.header.mhod_type
        assert kind in {1, 3, 4, 22, 23, 28, 29, 200, 201, 202}
        assert re.fullmatch(
            r"Fixture [A-Za-z0-9 .-]+|The Zeta|Thistle", chunk.payload.value
        ), "Unreviewed text in anonymized fixture"
        return new_string_mhod(kind, chunk.payload.value)
    definition = DATABASE_DEFINITION.chunk_definition(marker)
    assert definition is not None
    if isinstance(chunk.payload, MhodLibraryIndexPayload):
        assert marker == b"mhod"
        assert isinstance(chunk.header, MhodHeader)
        assert chunk.header.mhod_type == 52
        return new_itunes_chunk(
            definition,
            chunk.header,
            prefix=MhodLibraryIndexPrefix(sort_type=36),
            payload=MhodLibraryIndexPayload(chunk.payload.indices, b""),
        )
    assert chunk.payload is None, "Opaque data is forbidden in anonymized captures"
    return new_itunes_chunk(
        definition,
        chunk.header,
        children=tuple(_clean_chunk(c) for c in chunk.children),
    )


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "iTunesDB").glob("captured-*.b64")), ids=lambda p: p.name
)
def test_captured_fixtures_contain_only_fabricated_allowlisted_data(path: Path) -> None:
    data = base64.b64decode(path.read_bytes())
    document = parse_iTunesDB(data)
    tracks = [s.chunk.header for s in document.find_chunks(MhitHeader)]
    assert {t.track_id for t in tracks} == set(range(1, len(tracks) + 1))
    assert all(t.db_track_id == 10000 + t.track_id for t in tracks)
    albums = [s.chunk.header for s in document.find_chunks(MhiaHeader)]
    assert {a.album_id for a in albums} == set(range(100, 100 + len(albums)))
    assert all(a.sql_id == 20000 + a.album_id - 100 for a in albums)
    assert all(
        a.album_track_db_id in {0, *(t.db_track_id for t in tracks)} for a in albums
    )
    assert all(
        s.chunk.header.playlist_id == 1 for s in document.find_chunks(MhypHeader)
    )
    manifest = json.loads(path.with_suffix(".json").read_text())
    assert manifest["anonymized"] is True
    assert "source_track_ids" not in manifest
    # Fresh construction must reproduce every byte. This catches copied padding,
    # unknown payloads, URL/account MHODs, and hidden raw metadata, not just emails.
    assert write_iTunesDB(chunk_as(_clean_chunk(document), MhbdHeader)) == data
