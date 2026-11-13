"""Nano 5 uses saved SQLite order, not binary Playlist order or Host collation."""

import sqlite3
from contextlib import closing

import pytest
from tests.iPodDB.alarm_fixtures import nano5_sources

from iPodDB.SQLiteDB.alarm_playlists import project_sqlite_alarm_playlists


def test_sqlite_order_filters_and_saved_otg() -> None:
    result = project_sqlite_alarm_playlists(*nano5_sources())
    assert result.complete, result.issues
    assert not result.has_master
    assert [(row.index, row.playlist_id, row.name) for row in result.playlists] == [
        (0, 20, "Zebra"),
        (1, 30, "Alpha"),
        (2, 70, "On-The-Go 1"),
    ]


def test_eligible_primary_moves_to_front() -> None:
    result = project_sqlite_alarm_playlists(*nano5_sources(primary=30))
    assert result.complete
    assert [row.playlist_id for row in result.playlists] == [30, 20, 70]


def test_ambiguous_primary_source_never_chooses_arbitrary_row() -> None:
    source, dynamic = nano5_sources()
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(source)
        connection.execute(
            "INSERT INTO db_info(pid,primary_container_pid) VALUES(2,30)"
        )
        connection.commit()
        source = connection.serialize()
    result = project_sqlite_alarm_playlists(source, dynamic)
    assert not result.complete and result.issues and not result.playlists


@pytest.mark.parametrize(
    "media,eligible",
    (
        (0, True),
        (1, True),
        (2, False),
        (4, True),
        (8, True),
        (16, True),
        (32, True),
        (64, False),
        (128, True),
        (256, True),
        (32768, False),
        (1 << 20, True),
        (1 << 21, True),
        (2 | 32, True),
    ),
)
def test_native_media_conversion(media: int, eligible: bool) -> None:
    source, dynamic = nano5_sources()
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(source)
        connection.execute("UPDATE container SET media_kinds=? WHERE pid=20", (media,))
        connection.commit()
        source = connection.serialize()
    result = project_sqlite_alarm_playlists(source, dynamic)
    assert result.complete, result.issues
    assert (20 in [row.playlist_id for row in result.playlists]) is eligible


@pytest.mark.parametrize("which", (0, 1))
def test_corrupt_companion_never_yields_partial_indices(which: int) -> None:
    sources = list(nano5_sources())
    sources[which] = b"bad database"
    result = project_sqlite_alarm_playlists(*sources)
    assert not result.complete and result.issues and not result.playlists


@pytest.mark.parametrize(
    "pid,primary,complete", ((30, 100, False), (40, 100, True), (30, 30, True))
)
def test_only_ties_between_selectable_nonprimary_rows_are_ambiguous(
    pid: int, primary: int, complete: bool
) -> None:
    source, dynamic = nano5_sources(primary=primary)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(source)
        connection.execute("UPDATE container SET name_order=1 WHERE pid=?", (pid,))
        connection.commit()
        source = connection.serialize()
    result = project_sqlite_alarm_playlists(source, dynamic)
    assert result.complete is complete
