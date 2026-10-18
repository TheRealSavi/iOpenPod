"""Firmware metadata survives generation while edited CDB values take effect."""

import sqlite3
from dataclasses import replace

import pytest
from tests.iPodDB.SQLiteDB.sqlite_test_support import (
    sample_snapshot,
    sqlite_rows,
    sqlite_value,
)

from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.database import build_sqlite_databases
from iPodDB.SQLiteDB.inputs import SQLiteNativeMetadata, SQLiteSource


def test_refresh_retains_version_schema_and_unprojected_metadata() -> None:
    snapshot = sample_snapshot()
    baseline = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    connection = sqlite3.connect(":memory:")
    connection.deserialize(baseline.library)
    connection.executescript("""
        UPDATE version_info SET minor=117,device_update_level=1100;
        ALTER TABLE version_info ADD COLUMN future_version BLOB;
        UPDATE version_info SET future_version=X'010203';
        ALTER TABLE item ADD COLUMN future_item TEXT DEFAULT 'new';
        UPDATE item SET future_item='retained',genius_id=1234;
        INSERT INTO store_info (item_pid,store_item_id) SELECT pid,789 FROM item;
        CREATE TABLE future_metadata (value TEXT);
        INSERT INTO future_metadata VALUES ('keep me');
        PRAGMA user_version=77;
    """)
    connection.commit()
    retained = tuple(
        SQLiteSource(name, connection.serialize() if name == "Library.itdb" else data)
        for name, data in baseline.artifacts()
        if name.endswith(".itdb")
    )
    connection.close()
    desired = replace(snapshot, tracks=(replace(snapshot.tracks[0], title="Edited"),))
    result = build_sqlite_databases(
        desired, database_id=42, checksum=WriteChecksum.NONE, retained=retained
    )
    assert sqlite_rows(
        result.library,
        "SELECT minor,device_update_level,future_version FROM version_info",
    ) == ((117, 1100, b"\x01\x02\x03"),)
    assert sqlite_rows(
        result.library, "SELECT title,future_item,genius_id FROM item"
    ) == (("Edited", "retained", 1234),)
    assert sqlite_value(result.library, "SELECT store_item_id FROM store_info") == 789
    assert (
        sqlite_value(result.library, "SELECT value FROM future_metadata") == "keep me"
    )
    assert sqlite_value(result.library, "PRAGMA user_version") == 77


def test_sqlite_only_lyrics_survive_but_explicit_clears_and_deletions_win() -> None:
    snapshot = sample_snapshot()
    baseline = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    track = replace(
        snapshot.tracks[0],
        metadata=replace(snapshot.tracks[0].metadata, lyrics="", chapters=()),
    )
    snapshot = replace(snapshot, tracks=(track,))
    retained = (SQLiteSource("Extras.itdb", baseline.extras),)
    result = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE, retained=retained
    )
    assert sqlite_value(result.extras, "SELECT lyrics FROM lyrics") == "words"
    assert sqlite_value(result.library, "SELECT has_lyrics FROM item") == 1
    pid = track.ipod.db_track_id if track.ipod else track.track_id
    cleared = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=retained,
        cleared_lyrics=frozenset((pid,)),
        cleared_chapters=frozenset((pid,)),
    )
    assert sqlite_rows(cleared.extras, "SELECT * FROM lyrics") == ()
    assert sqlite_rows(cleared.extras, "SELECT * FROM chapter") == ()
    removed = build_sqlite_databases(
        replace(snapshot, tracks=(), playlists=()),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=retained,
    )
    assert sqlite_rows(removed.extras, "SELECT * FROM lyrics") == ()


def test_dynamic_played_state_uses_native_state_even_without_completed_plays() -> None:
    snapshot = sample_snapshot()
    track = replace(
        snapshot.tracks[0],
        play_count=0,
        metadata=replace(snapshot.tracks[0].metadata, played=True),
    )
    result = build_sqlite_databases(
        replace(snapshot, tracks=(track,)), database_id=42, checksum=WriteChecksum.NONE
    )
    assert sqlite_value(result.dynamic, "SELECT has_been_played FROM item_stats") == 1


def test_captured_nano5_schema_needs_no_version_or_column_migration() -> None:
    snapshot = sample_snapshot()
    baseline = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    retained: list[SQLiteSource] = []
    schemas: dict[str, tuple[tuple[object, ...], ...]] = {}
    for name, data in baseline.artifacts():
        if not name.endswith(".itdb"):
            continue
        connection = sqlite3.connect(":memory:")
        connection.deserialize(data)
        if name == "Library.itdb":
            connection.executescript("""
                ALTER TABLE album DROP COLUMN has_movies;
                ALTER TABLE album DROP COLUMN item_count;
                ALTER TABLE genre_map DROP COLUMN compilation_count_calc;
                UPDATE version_info SET minor=117,device_update_level=1100;
            """)
        elif name == "Dynamic.itdb":
            connection.execute("ALTER TABLE item_stats DROP COLUMN genius_id")
        connection.commit()
        original = connection.serialize()
        connection.close()
        schemas[name] = sqlite_rows(
            original, "SELECT sql FROM sqlite_master ORDER BY name"
        )
        retained.append(SQLiteSource(name, original))
    result = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=tuple(retained),
    )
    for name, data in result.artifacts():
        if name in schemas:
            assert (
                sqlite_rows(data, "SELECT sql FROM sqlite_master ORDER BY name")
                == schemas[name]
            )
    assert sqlite_rows(result.library, "SELECT * FROM version_info") == (
        (1, 1, 117, 0, 0, 1100, 2),
    )


def test_reordered_groups_keep_their_own_unknown_metadata() -> None:
    snapshot = sample_snapshot()
    first = snapshot.tracks[0]
    second = replace(
        first, track_id=8, album="Other album", artist="Other artist", ipod=None
    )
    snapshot = replace(snapshot, tracks=(first, second))
    baseline = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    connection = sqlite3.connect(":memory:")
    connection.deserialize(baseline.library)
    connection.executescript("""
        ALTER TABLE album ADD COLUMN future_value TEXT;
        UPDATE album SET future_value='retained ' || name;
    """)
    connection.commit()
    retained = (SQLiteSource("Library.itdb", connection.serialize()),)
    connection.close()
    result = build_sqlite_databases(
        replace(snapshot, tracks=(second, first)),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=retained,
    )
    assert sqlite_rows(
        result.library, "SELECT name,future_value FROM album ORDER BY name"
    ) == (
        ("Album", "retained Album"),
        ("Other album", "retained Other album"),
    )


def test_native_database_and_master_identities_and_version_are_used() -> None:
    result = build_sqlite_databases(
        sample_snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        native=SQLiteNativeMetadata(
            database_id=123,
            master_id=456,
            database_version=117,
            master_date_created=1_700_000_000,
            master_date_modified=1_700_000_100,
        ),
    )
    assert sqlite_rows(
        result.library, "SELECT pid,primary_container_pid FROM db_info"
    ) == ((123, 456),)
    assert sqlite_value(result.library, "SELECT minor FROM version_info") == 117
    assert sqlite_rows(
        result.library, "SELECT date_created,date_modified FROM container WHERE pid=456"
    ) == ((721692800, 721692900),)


def test_unreadable_existing_sqlite_is_not_silently_replaced() -> None:
    with pytest.raises(ValueError, match="SQLite Library generation failed"):
        build_sqlite_databases(
            sample_snapshot(),
            database_id=42,
            checksum=WriteChecksum.NONE,
            retained=(SQLiteSource("Library.itdb", b"damaged SQLite"),),
        )


def test_video_file_facts_survive_metadata_edits_but_not_media_replacement() -> None:
    snapshot = sample_snapshot()
    track = snapshot.tracks[0]
    assert track.ipod is not None
    pid = track.ipod.db_track_id
    track = replace(track, ipod=replace(track.ipod, media_type_code=2))
    snapshot = replace(snapshot, tracks=(track,))
    baseline = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    connection = sqlite3.connect(":memory:")
    connection.deserialize(baseline.library)
    connection.executescript("""
        UPDATE avformat_info SET channels=6;
        UPDATE video_info SET audio_language=9;
        INSERT INTO video_characteristics (item_pid,sub_id,track_id,height,width)
            SELECT pid,0,1,480,640 FROM item;
    """)
    connection.commit()
    retained = (SQLiteSource("Library.itdb", connection.serialize()),)
    connection.close()
    result = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE, retained=retained
    )
    assert sqlite_value(result.library, "SELECT channels FROM avformat_info") == 6
    assert sqlite_value(result.library, "SELECT audio_language FROM video_info") == 9
    assert sqlite_rows(
        result.library, "SELECT height,width FROM video_characteristics"
    ) == ((480, 640),)
    replaced = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=retained,
        replaced_tracks=frozenset((pid,)),
    )
    assert sqlite_value(replaced.library, "SELECT channels FROM avformat_info") == 0
    assert (
        sqlite_value(replaced.library, "SELECT audio_language FROM video_info") is None
    )
    assert sqlite_rows(replaced.library, "SELECT * FROM video_characteristics") == ()
