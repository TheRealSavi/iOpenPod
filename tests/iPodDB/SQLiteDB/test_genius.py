"""Native Genius tables and cross-companion relationships survive regeneration."""

import sqlite3
from dataclasses import replace

import pytest
from tests.iPodDB.SQLiteDB.sqlite_test_support import (
    sample_snapshot,
    sqlite_rows,
    sqlite_value,
)

from iPodDB.genius import (
    GeniusMetadata,
    GeniusPayloadKind,
    GeniusSimilarities,
    OpaqueGeniusPayload,
    make_no_rule_genius_config,
)
from iPodDB.library import LibrarySnapshot, PlaylistKind
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.database import build_sqlite_databases
from iPodDB.SQLiteDB.genius import (
    GeniusConfigRow,
    GeniusData,
    GeniusDatabase,
    GeniusMetadataRow,
    GeniusSimilaritiesRow,
    parse_genius_database,
    serialize_genius_database,
)
from iPodDB.SQLiteDB.genius_projection import read_sqlite_genius_state
from iPodDB.SQLiteDB.inputs import (
    SQLiteGeniusMix,
    SQLiteGeniusTrack,
    SQLiteGeniusUpdate,
    SQLiteSource,
)


def _data() -> GeniusData:
    return GeniusData(
        (GeniusConfigRow(1, 2, 25, 10, make_no_rule_genius_config()),),
        tuple(
            GeniusMetadataRow(gid, 2, GeniusMetadata((gid, 2, 3, 4)))
            for gid in (1001, 1002)
        ),
        (
            GeniusSimilaritiesRow(1001, 2, GeniusSimilarities((1002,))),
            GeniusSimilaritiesRow(1002, 2, GeniusSimilarities((1001,))),
        ),
    )


def _snapshot() -> LibrarySnapshot:
    snapshot = sample_snapshot()
    return replace(
        snapshot,
        tracks=(
            *snapshot.tracks,
            replace(snapshot.tracks[0], track_id=8, title="Second", ipod=None),
        ),
    )


def _update() -> SQLiteGeniusUpdate:
    return SQLiteGeniusUpdate(
        _data(),
        (SQLiteGeniusTrack(7, 1001), SQLiteGeniusTrack(8, 1002)),
        (SQLiteGeniusMix(999, "Test Mix", (7, 8, 7), 7),),
    )


def _build(snapshot: LibrarySnapshot) -> SQLiteDatabaseSet:
    return build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE, genius_update=_update()
    )


def _sources(result: SQLiteDatabaseSet) -> tuple[SQLiteSource, ...]:
    return tuple(
        SQLiteSource(name, data)
        for name, data in result.artifacts()
        if name.endswith(".itdb")
    )


def _changed(data: bytes, sql: str) -> bytes:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(data)
    connection.executescript(sql)
    connection.commit()
    result = connection.serialize()
    connection.close()
    return result


def test_document_round_trip_preserves_exact_bytes_and_unknown_schema() -> None:
    original = serialize_genius_database(GeniusDatabase(_data()))
    assert original[18:20] == b"\x01\x01"
    assert int.from_bytes(original[24:28], "big") > 0
    assert original[24:28] == original[92:96]
    assert int.from_bytes(original[96:100], "big") > 0
    original = _changed(
        original,
        """
        ALTER TABLE genius_metadata ADD COLUMN future BLOB DEFAULT X'0102';
        UPDATE genius_metadata SET future=X'0908' WHERE genius_id=1001;
        CREATE TABLE unrelated (value TEXT);
        INSERT INTO unrelated VALUES ('keep');
        CREATE INDEX future_index ON genius_metadata(version);
        PRAGMA user_version=123;
    """,
    )
    document = parse_genius_database(original)
    assert serialize_genius_database(document) == original
    desired = replace(
        document.data,
        metadata=(
            replace(document.data.metadata[0], payload=GeniusMetadata((11, 12))),
            document.data.metadata[1],
        ),
    )
    written = serialize_genius_database(document, desired)
    assert parse_genius_database(written).data == desired
    assert sqlite_rows(
        written, "SELECT genius_id,future FROM genius_metadata ORDER BY genius_id"
    ) == ((1001, b"\x09\x08"), (1002, b"\x01\x02"))
    assert sqlite_value(written, "SELECT value FROM unrelated") == "keep"
    assert sqlite_value(written, "PRAGMA user_version") == 123
    assert sqlite_rows(
        written, "SELECT sql FROM sqlite_master ORDER BY name"
    ) == sqlite_rows(original, "SELECT sql FROM sqlite_master ORDER BY name")


def test_classic_extras_tables_and_null_future_payloads_are_retained() -> None:
    original = serialize_genius_database(GeniusDatabase(_data()))
    original = _changed(
        original,
        """
        CREATE TABLE lyrics (item_pid INTEGER PRIMARY KEY, lyrics TEXT);
        INSERT INTO lyrics VALUES (99,'untouched');
        INSERT INTO genius_metadata VALUES (2001,NULL,NULL);
        INSERT INTO genius_similarities VALUES (2001,99,X'010203');
    """,
    )
    document = parse_genius_database(original)
    assert document.data.metadata[-1].payload is None
    assert isinstance(document.data.similarities[-1].payload, OpaqueGeniusPayload)
    assert serialize_genius_database(document) == original
    changed = serialize_genius_database(document, replace(document.data, configs=()))
    assert sqlite_rows(changed, "SELECT * FROM lyrics") == ((99, "untouched"),)
    assert sqlite_rows(
        changed, "SELECT * FROM genius_metadata WHERE genius_id=2001"
    ) == ((2001, None, None),)
    assert sqlite_rows(
        changed, "SELECT * FROM genius_similarities WHERE genius_id=2001"
    ) == ((2001, 99, b"\x01\x02\x03"),)


def test_document_rejects_duplicate_ids_version_mismatch_and_unreadable_source() -> (
    None
):
    data = _data()
    with pytest.raises(ValueError, match="Duplicate Genius identity"):
        serialize_genius_database(
            GeniusDatabase(replace(data, metadata=data.metadata * 2))
        )
    with pytest.raises(ValueError, match="version differs"):
        serialize_genius_database(
            GeniusDatabase(
                replace(data, metadata=(replace(data.metadata[0], version=3),))
            )
        )
    for bad in (b"", b"not SQLite"):
        with pytest.raises(ValueError, match="Invalid Genius SQLite"):
            parse_genius_database(bad)


def test_authoring_updates_all_three_artifacts_and_reads_native_mix_state() -> None:
    result = _build(_snapshot())
    state = read_sqlite_genius_state(result.library, result.dynamic, result.genius)
    assert state.data == _data()
    assert dict(state.track_genius_ids) == {0xF123456789ABCDEF: 1001, 8: 1002}
    assert state.mixes[0].item_pids == (0xF123456789ABCDEF, 8, 0xF123456789ABCDEF)
    assert state.mixes[0].seed_pids == (0xF123456789ABCDEF,)
    assert sqlite_rows(
        result.library,
        "SELECT distinguished_kind,smart_is_genius FROM container WHERE pid=999",
    ) == ((32, 1),)
    assert sqlite_rows(
        result.library,
        "SELECT smart_is_dynamic,smart_is_filtered,smart_limit_kind,smart_limit_value FROM container WHERE pid=999",
    ) == ((1, 1, 2, 25),)
    assert sqlite_rows(
        result.dynamic, "SELECT * FROM container_ui WHERE container_pid=999"
    ) == ((999, 1, 0, 52, 0, 0, 0),)


@pytest.mark.parametrize("graph_refresh", [False, True])
def test_metadata_or_graph_refresh_preserves_mix_membership_ui_and_unknown_columns(
    graph_refresh: bool,
) -> None:
    snapshot = _snapshot()
    baseline = _build(snapshot)
    library = _changed(
        baseline.library,
        """
        ALTER TABLE container ADD COLUMN future TEXT;
        UPDATE container SET future='mix future' WHERE pid=999;
        ALTER TABLE item_to_container ADD COLUMN future_member INTEGER;
        UPDATE item_to_container SET shuffle_order=17,future_member=88 WHERE container_pid=999;
        ALTER TABLE container_seed ADD COLUMN future_seed TEXT;
        UPDATE container_seed SET seed_order=7,future_seed='seed future' WHERE container_pid=999;
    """,
    )
    dynamic = _changed(
        baseline.dynamic,
        "UPDATE container_ui SET play_order=7,shuffle_items=1 WHERE container_pid=999",
    )
    retained = _sources(replace(baseline, library=library, dynamic=dynamic))
    result = build_sqlite_databases(
        replace(
            snapshot,
            tracks=(replace(snapshot.tracks[0], title="Edited"), snapshot.tracks[1]),
        ),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=retained,
        genius_update=replace(_update(), mixes=None) if graph_refresh else None,
    )
    assert sqlite_rows(
        result.library, "SELECT * FROM container WHERE pid=999"
    ) == sqlite_rows(library, "SELECT * FROM container WHERE pid=999")
    assert sqlite_rows(
        result.library,
        "SELECT * FROM item_to_container WHERE container_pid=999 ORDER BY physical_order",
    ) == sqlite_rows(
        library,
        "SELECT * FROM item_to_container WHERE container_pid=999 ORDER BY physical_order",
    )
    assert sqlite_rows(
        result.dynamic, "SELECT * FROM container_ui WHERE container_pid=999"
    ) == sqlite_rows(dynamic, "SELECT * FROM container_ui WHERE container_pid=999")
    assert sqlite_rows(
        result.library, "SELECT * FROM container_seed WHERE container_pid=999"
    ) == sqlite_rows(library, "SELECT * FROM container_seed WHERE container_pid=999")
    assert parse_genius_database(result.genius).data == _data()


@pytest.mark.parametrize("replacement", [False, True])
def test_graph_only_refresh_prunes_mix_members_without_new_assignments(
    replacement: bool,
) -> None:
    baseline = _build(_snapshot())
    library = _changed(
        baseline.library,
        """
        ALTER TABLE item_to_container ADD COLUMN future_member INTEGER;
        UPDATE item_to_container SET shuffle_order=17,future_member=88 WHERE container_pid=999;
        INSERT INTO container_seed VALUES (23,-1070935975390360081,4);
    """,
    )
    data = GeniusData(
        _data().configs,
        (GeniusMetadataRow(2002, 2, GeniusMetadata((12, 13))),),
        (GeniusSimilaritiesRow(2002, 2, GeniusSimilarities(())),),
    )
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(replace(baseline, library=library)),
        genius_update=SQLiteGeniusUpdate(data, (SQLiteGeniusTrack(8, 2002),)),
        replaced_tracks=frozenset((8,)) if replacement else frozenset(),
    )
    assert parse_genius_database(result.genius).data == data
    assert sqlite_rows(
        result.library,
        "SELECT * FROM item_to_container WHERE container_pid=999 ORDER BY physical_order",
    ) == ((8, 999, 1, 17, 88),)
    assert (
        sqlite_rows(
            result.library, "SELECT * FROM container_seed WHERE container_pid=999"
        )
        == ()
    )
    assert sqlite_rows(
        result.library, "SELECT * FROM container_seed WHERE container_pid=23"
    ) == ((23, -1070935975390360081, 4),)
    assert sqlite_rows(
        result.library, "SELECT * FROM item_to_container WHERE container_pid=23"
    ) == sqlite_rows(library, "SELECT * FROM item_to_container WHERE container_pid=23")


def test_graph_only_clear_keeps_empty_native_mix_and_ui() -> None:
    baseline = _build(_snapshot())
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(baseline),
        genius_update=SQLiteGeniusUpdate(GeniusData()),
    )
    state = read_sqlite_genius_state(result.library, result.dynamic, result.genius)
    assert state.data == GeniusData()
    assert state.track_genius_ids == ()
    assert len(state.mixes) == 1
    assert state.mixes[0].container_id == 999
    assert state.mixes[0].item_pids == state.mixes[0].seed_pids == ()
    assert sqlite_rows(
        result.dynamic, "SELECT * FROM container_ui WHERE container_pid=999"
    ) == sqlite_rows(
        baseline.dynamic, "SELECT * FROM container_ui WHERE container_pid=999"
    )


def test_graph_only_refresh_never_creates_mix_containers() -> None:
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        genius_update=replace(_update(), mixes=None),
    )
    assert (
        read_sqlite_genius_state(result.library, result.dynamic, result.genius).mixes
        == ()
    )


def test_graph_only_refresh_reserves_retained_mix_identity() -> None:
    baseline = _build(_snapshot())
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        playlists=(replace(snapshot.playlists[0], playlist_id=999),),
    )
    with pytest.raises(ValueError, match="conflicts with a native CDB container"):
        build_sqlite_databases(
            snapshot,
            database_id=42,
            checksum=WriteChecksum.NONE,
            retained=_sources(baseline),
            genius_update=replace(_update(), mixes=None),
        )


@pytest.mark.parametrize("seed", [None, 8])
def test_saved_genius_playlist_marker_and_seed_survive_metadata_refresh(
    seed: int | None,
) -> None:
    baseline = _build(_snapshot())
    library = _changed(
        baseline.library,
        """
        UPDATE container SET smart_is_genius=1 WHERE pid=23;
        INSERT INTO container_seed VALUES (23,8,0);
    """,
    )
    snapshot = _snapshot()
    canonical = replace(
        snapshot,
        playlists=(
            replace(
                snapshot.playlists[0],
                kind=PlaylistKind.GENIUS,
                genius_seed_persistent_id=seed,
            ),
        ),
    )
    result = build_sqlite_databases(
        canonical,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(replace(baseline, library=library)),
    )
    assert (
        sqlite_value(
            result.library, "SELECT smart_is_genius FROM container WHERE pid=23"
        )
        == 1
    )
    assert sqlite_rows(
        result.library, "SELECT * FROM container_seed WHERE container_pid=23"
    ) == ((23, 8, 0),)


def test_canonical_genius_marker_and_known_seed_project_without_sqlite_source() -> None:
    snapshot = _snapshot()
    canonical = replace(
        snapshot,
        playlists=(
            replace(
                snapshot.playlists[0],
                kind=PlaylistKind.GENIUS,
                genius_seed_persistent_id=8,
            ),
        ),
    )
    result = build_sqlite_databases(
        canonical, database_id=42, checksum=WriteChecksum.NONE
    )
    assert (
        sqlite_value(
            result.library, "SELECT smart_is_genius FROM container WHERE pid=23"
        )
        == 1
    )
    assert sqlite_rows(result.library, "SELECT * FROM container_seed") == ((23, 8, 0),)


def test_known_canonical_seed_replaces_stale_sqlite_seed_but_preserves_unknown_columns() -> (
    None
):
    snapshot = _snapshot()
    baseline = _build(snapshot)
    library = _changed(
        baseline.library,
        """
        ALTER TABLE container_seed ADD COLUMN future TEXT DEFAULT 'new';
        INSERT INTO container_seed VALUES (23,8,4,'known row');
        INSERT INTO container_seed VALUES (23,-1070935975390360081,0,'stale row');
    """,
    )
    canonical = replace(
        snapshot,
        playlists=(
            replace(
                snapshot.playlists[0],
                kind=PlaylistKind.GENIUS,
                genius_seed_persistent_id=8,
            ),
        ),
    )
    result = build_sqlite_databases(
        canonical,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(replace(baseline, library=library)),
    )
    assert (
        sqlite_value(
            result.library, "SELECT smart_is_genius FROM container WHERE pid=23"
        )
        == 1
    )
    assert sqlite_rows(
        result.library, "SELECT * FROM container_seed WHERE container_pid=23"
    ) == ((23, 8, 0, "known row"),)


def test_missing_known_canonical_seed_is_not_written_as_a_dangling_reference() -> None:
    snapshot = _snapshot()
    canonical = replace(
        snapshot,
        playlists=(
            replace(
                snapshot.playlists[0],
                kind=PlaylistKind.GENIUS,
                genius_seed_persistent_id=9999,
            ),
        ),
    )
    with pytest.raises(ValueError, match="seed references a missing Track"):
        build_sqlite_databases(canonical, database_id=42, checksum=WriteChecksum.NONE)


def test_explicit_mix_edit_retains_unrequested_container_and_ui_values() -> None:
    baseline = _build(_snapshot())
    library = _changed(
        baseline.library,
        """
        UPDATE container SET date_created=111,date_modified=222,smart_is_dynamic=0,
            smart_is_filtered=0,smart_is_genius=0,smart_limit_value=13 WHERE pid=999;
        ALTER TABLE container ADD COLUMN future TEXT;
        UPDATE container SET future='keep' WHERE pid=999;
    """,
    )
    dynamic = _changed(
        baseline.dynamic,
        "UPDATE container_ui SET play_order=7,shuffle_items=1 WHERE container_pid=999",
    )
    update = replace(_update(), mixes=(SQLiteGeniusMix(999, "Renamed", (8,), 8),))
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(replace(baseline, library=library, dynamic=dynamic)),
        genius_update=update,
    )
    assert sqlite_rows(
        result.library,
        "SELECT name,date_created,date_modified,smart_is_dynamic,smart_is_filtered,smart_is_genius,smart_limit_value,future FROM container WHERE pid=999",
    ) == (("Renamed", 111, 222, 0, 0, 0, 13, "keep"),)
    assert sqlite_rows(
        result.dynamic, "SELECT * FROM container_ui WHERE container_pid=999"
    ) == sqlite_rows(dynamic, "SELECT * FROM container_ui WHERE container_pid=999")
    assert sqlite_rows(
        result.library, "SELECT item_pid FROM item_to_container WHERE container_pid=999"
    ) == ((8,),)
    assert sqlite_rows(
        result.library, "SELECT item_pid FROM container_seed WHERE container_pid=999"
    ) == ((8,),)


def test_unsigned_genius_identity_keeps_signed_sqlite_storage_and_unsigned_edges() -> (
    None
):
    gid = (1 << 64) - 10
    data = GeniusData(
        _data().configs,
        (GeniusMetadataRow(gid, 2, GeniusMetadata((0,))),),
        (GeniusSimilaritiesRow(gid, 2, GeniusSimilarities((gid,))),),
    )
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        genius_update=SQLiteGeniusUpdate(data, (SQLiteGeniusTrack(8, gid),)),
    )
    assert sqlite_value(result.library, "SELECT genius_id FROM item WHERE pid=8") == -10
    assert sqlite_value(result.genius, "SELECT genius_id FROM genius_metadata") == -10
    assert parse_genius_database(result.genius).data == data


@pytest.mark.parametrize("replacement", [False, True])
def test_removed_or_replaced_tracks_leave_no_genius_edges_or_mix_seeds(
    replacement: bool,
) -> None:
    snapshot = _snapshot()
    baseline = _build(snapshot)
    desired = (
        snapshot if replacement else replace(snapshot, tracks=(snapshot.tracks[0],))
    )
    result = build_sqlite_databases(
        desired,
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(baseline),
        replaced_tracks=frozenset((8,)) if replacement else frozenset(),
    )
    data = parse_genius_database(result.genius).data
    assert tuple(row.genius_id for row in data.metadata) == (1001,)
    assert data.similarities == (
        GeniusSimilaritiesRow(1001, 2, GeniusSimilarities(())),
    )
    assert sqlite_rows(
        result.library,
        "SELECT item_pid FROM item_to_container WHERE container_pid=999 ORDER BY physical_order",
    ) == ((-1070935975390360081,), (-1070935975390360081,))
    if replacement:
        assert (
            sqlite_value(result.library, "SELECT genius_id FROM item WHERE pid=8") == 0
        )
        assert (
            sqlite_value(
                result.dynamic, "SELECT genius_id FROM item_stats WHERE item_pid=8"
            )
            == 0
        )


def test_track_removal_rejects_opaque_retained_edges() -> None:
    snapshot = _snapshot()
    baseline = _build(snapshot)
    opaque = OpaqueGeniusPayload(
        GeniusPayloadKind.SIMILARITIES, 99, b"opaque", "future"
    )
    document = parse_genius_database(baseline.genius)
    genius = serialize_genius_database(
        document,
        replace(
            document.data,
            similarities=(
                GeniusSimilaritiesRow(1001, 99, opaque),
                document.data.similarities[1],
            ),
        ),
    )
    with pytest.raises(ValueError, match="opaque similarities"):
        build_sqlite_databases(
            replace(snapshot, tracks=(snapshot.tracks[0],)),
            database_id=42,
            checksum=WriteChecksum.NONE,
            retained=_sources(replace(baseline, genius=genius)),
        )


def test_explicit_remapping_replaces_ids_edges_and_mixes_without_schema_migration() -> (
    None
):
    baseline = _build(_snapshot())
    dynamic = _changed(baseline.dynamic, "ALTER TABLE item_stats DROP COLUMN genius_id")
    data = GeniusData(
        _data().configs,
        (GeniusMetadataRow(9001, 2, GeniusMetadata((0,))),),
        (GeniusSimilaritiesRow(9001, 2, GeniusSimilarities(())),),
    )
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(replace(baseline, dynamic=dynamic)),
        genius_update=SQLiteGeniusUpdate(
            data,
            (SQLiteGeniusTrack(8, 9001),),
            (SQLiteGeniusMix(1000, "Replacement Mix", (8,)),),
        ),
    )
    assert sqlite_rows(
        result.library, "SELECT pid FROM container WHERE distinguished_kind=32"
    ) == ((1000,),)
    assert sqlite_rows(
        result.library, "SELECT pid,genius_id FROM item ORDER BY pid"
    ) == ((-1070935975390360081, 0), (8, 9001))
    assert "genius_id" not in {
        row[1] for row in sqlite_rows(result.dynamic, "PRAGMA table_info(item_stats)")
    }
    assert parse_genius_database(result.genius).data == data


def test_explicit_clear_removes_known_genius_state() -> None:
    baseline = _build(_snapshot())
    result = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        retained=_sources(baseline),
        genius_update=SQLiteGeniusUpdate(GeniusData(), mixes=()),
    )
    assert parse_genius_database(result.genius).data == GeniusData()
    assert (
        sqlite_rows(
            result.library, "SELECT pid FROM container WHERE distinguished_kind=32"
        )
        == ()
    )
    assert sqlite_rows(result.library, "SELECT genius_id FROM item") == ((0,), (0,))
    assert sqlite_rows(result.library, "SELECT * FROM container_seed") == ()


@pytest.mark.parametrize(
    "invalid",
    [
        replace(
            _update(), tracks=(SQLiteGeniusTrack(7, 1001), SQLiteGeniusTrack(7, 1002))
        ),
        replace(
            _update(), tracks=(SQLiteGeniusTrack(7, 1001), SQLiteGeniusTrack(8, 1001))
        ),
        replace(
            _update(), tracks=(SQLiteGeniusTrack(7, 1001), SQLiteGeniusTrack(9, 1002))
        ),
        replace(_update(), mixes=(SQLiteGeniusMix(23, "Conflict", (7,)),)),
        replace(_update(), mixes=(SQLiteGeniusMix(999, "Missing seed", (9,)),)),
        replace(
            _update(),
            mixes=(SQLiteGeniusMix(999, "Wrong compatibility seed", (7,), 8),),
        ),
    ],
)
def test_incoherent_authoring_is_rejected(invalid: SQLiteGeniusUpdate) -> None:
    with pytest.raises(ValueError):
        build_sqlite_databases(
            _snapshot(),
            database_id=42,
            checksum=WriteChecksum.NONE,
            genius_update=invalid,
        )
