"""Late-iPod artifacts retain ordinary file-backed SQLite header semantics."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from tests.iPodDB.SQLiteDB.test_database import (
    _snapshot,  # pyright: ignore[reportPrivateUsage]
)

from iPodDB.library import LibrarySnapshot
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB import database
from iPodDB.SQLiteDB.checksum import verify_locations_cbk

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("postprocess", [False, True])
def test_serialized_artifacts_match_file_backed_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    populated: bool,
    postprocess: bool,
) -> None:
    snapshot = _snapshot() if populated else LibrarySnapshot((), (), "Empty iPod")
    commands = (
        ('PRAGMA main.user_version=42; PRAGMA "Locations.itdb".user_version=7;',)
        if postprocess
        else ()
    )
    guid = bytes.fromhex("000A270012345678")
    actual = database.build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.HASHAB,
        firewire_guid=guid,
        postprocess_commands=commands,
    )
    file_index = 0

    def file_backed(schema: str) -> sqlite3.Connection:
        nonlocal file_index
        file_index += 1
        connection = sqlite3.connect(tmp_path / f"expected-{file_index}.itdb")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA encoding='UTF-8'")
        connection.executescript(schema)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(database, "_new", file_backed)
        expected = database.build_sqlite_databases(
            snapshot,
            database_id=42,
            checksum=WriteChecksum.HASHAB,
            firewire_guid=guid,
            postprocess_commands=commands,
        )

    for (name, actual_data), (_, expected_data) in zip(
        actual.artifacts(), expected.artifacts(), strict=True
    ):
        assert actual_data == expected_data, name
        if name.endswith(".itdb"):
            assert int.from_bytes(actual_data[24:28], "big") > 0
            assert actual_data[24:28] == actual_data[92:96]
            version = sqlite3.sqlite_version_info
            assert int.from_bytes(actual_data[96:100], "big") == (
                version[0] * 1_000_000 + version[1] * 1_000 + version[2]
            )
    assert verify_locations_cbk(actual, WriteChecksum.HASHAB, guid)


def test_simultaneous_generations_keep_independent_private_databases() -> None:
    snapshot = _snapshot()

    def generate(index: int) -> str:
        selected = replace(
            snapshot, tracks=(replace(snapshot.tracks[0], title=f"Track {index}"),)
        )
        artifacts = database.build_sqlite_databases(
            selected, database_id=index + 1, checksum=WriteChecksum.NONE
        )
        connection = sqlite3.connect(":memory:")
        try:
            connection.deserialize(artifacts.library)
            result: str = connection.execute("SELECT title FROM item").fetchone()[0]
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as workers:
        titles = tuple(workers.map(generate, range(12)))
    assert titles == tuple(f"Track {index}" for index in range(12))


def test_live_connections_do_not_share_a_named_memory_database() -> None:
    first = database._new("CREATE TABLE marker (value TEXT)")  # pyright: ignore[reportPrivateUsage]
    second = database._new("CREATE TABLE marker (value TEXT)")  # pyright: ignore[reportPrivateUsage]
    try:
        first.execute("INSERT INTO marker VALUES ('first')")
        first.commit()
        assert second.execute("SELECT * FROM marker").fetchall() == []
    finally:
        first.close()
        second.close()
