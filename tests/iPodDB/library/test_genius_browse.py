"""Native Genius browsing is read-only and keeps identities and membership honest."""

import plistlib
import sqlite3
from dataclasses import replace

import pytest

from iPodDB.library import (
    IPodTrackDetails,
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    Track,
    playlist_entries,
)
from iPodDB.library.genius import (
    GeniusBrowse,
    GeniusCollectionKind,
    project_genius_browse,
)
from iPodDB.sidecars import GeniusPlaylist, PlaybackSidecar, create_genius_playlist

_HIGH_PID = (1 << 64) - 11


def _snapshot() -> LibrarySnapshot:
    return LibrarySnapshot(
        tuple(
            Track(
                index + 7,
                f"Track {index}",
                "Artist",
                "Album",
                1000,
                ipod=IPodTrackDetails(db_track_id=pid),
            )
            for index, pid in enumerate((_HIGH_PID, 22, 33))
        ),
        (),
    )


def _playlist() -> GeniusPlaylist:
    return GeniusPlaylist(
        1, "Saved Genius", _HIGH_PID, 1234, (0, 2, 0), (_HIGH_PID, 33, _HIGH_PID)
    )


def _sidecar(
    playlist: GeniusPlaylist | None = None, name: str = "GeniusPlaylist_1.plist"
) -> PlaybackSidecar:
    return PlaybackSidecar(
        name, create_genius_playlist(playlist or _playlist()).serialize()
    )


def _sqlite(sql: str = "") -> bytes:
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE container (pid INTEGER PRIMARY KEY, name TEXT, distinguished_kind INTEGER, name_order INTEGER);
        CREATE TABLE item_to_container (container_pid INTEGER, item_pid INTEGER, physical_order INTEGER);
        CREATE TABLE container_seed (container_pid INTEGER, item_pid INTEGER, seed_order INTEGER);
        INSERT INTO container VALUES (100,'First Mix',32,200);
        INSERT INTO container VALUES (101,'Second Mix',32,100);
        INSERT INTO container VALUES (102,'Ordinary Playlist',0,0);
        INSERT INTO item_to_container VALUES (100,33,0),(100,-11,1),(100,33,2),(101,22,0),(102,22,0);
        INSERT INTO container_seed VALUES (100,-11,0);
    """)
    if sql:
        connection.executescript(sql)
    connection.commit()
    result = connection.serialize()
    connection.close()
    return result


def test_saved_playlist_maps_persistent_ids_and_preserves_repeated_occurrences() -> (
    None
):
    snapshot = _snapshot()
    sidecar = _sidecar()
    before = snapshot, sidecar.data
    result = project_genius_browse(snapshot, (sidecar,))
    assert not result.issues
    assert len(result.collections) == 1
    collection = result.collections[0]
    assert collection.kind is GeniusCollectionKind.PLAYLIST
    assert collection.name == "Saved Genius"
    assert collection.track_ids == (7, 9, 7)
    assert collection.seed_track_id == 7
    assert collection.native_playlist_id is None
    assert collection.collection_id == "genius-playlist:geniusplaylist_1.plist"
    assert (snapshot, sidecar.data) == before
    assert snapshot.playlists == ()


def test_identity_only_variant_exposes_native_id_and_stable_identity() -> None:
    playlist = replace(
        _playlist(), track_master_indexes=None, playlist_persistent_id=(1 << 64) - 9
    )
    first = project_genius_browse(_snapshot(), (_sidecar(playlist),))
    renamed_file = project_genius_browse(
        _snapshot(), (_sidecar(playlist, "GeniusPlaylist_9.plist"),)
    )
    assert first == renamed_file
    assert first.collections[0].native_playlist_id == (1 << 64) - 9
    assert first.collections[0].collection_id == "genius-playlist:fffffffffffffff7"


def test_sqlite_library_alone_projects_mix_starting_tracks_in_native_order() -> None:
    result = project_genius_browse(_snapshot(), sqlite_library=_sqlite())
    assert not result.issues
    assert tuple(collection.name for collection in result.collections) == (
        "Second Mix",
        "First Mix",
    )
    assert all(
        collection.kind is GeniusCollectionKind.MIX for collection in result.collections
    )
    first, second = result.collections
    assert first.track_ids == (8,)
    assert first.seed_track_id is None
    assert second.track_ids == (9, 7, 9)
    assert second.seed_track_id == 7
    assert second.native_playlist_id == 100
    assert second.collection_id == "genius-mix:0000000000000064"


@pytest.mark.parametrize(
    "playlist,code",
    [
        (
            replace(_playlist(), track_persistent_ids=(_HIGH_PID, 999, _HIGH_PID)),
            "genius.missing_track",
        ),
        (replace(_playlist(), seed_track_persistent_id=999), "genius.missing_track"),
        (
            replace(_playlist(), track_master_indexes=(0, 1, 0)),
            "genius.position_mismatch",
        ),
        (
            replace(_playlist(), track_master_indexes=(0, 9, 0)),
            "genius.position_mismatch",
        ),
    ],
)
def test_invalid_saved_members_or_positions_do_not_produce_partial_playlists(
    playlist: GeniusPlaylist, code: str
) -> None:
    result = project_genius_browse(_snapshot(), (_sidecar(playlist),))
    assert not result.collections
    assert result.issues[0].code == code


def test_ambiguous_persistent_identity_is_not_resolved_arbitrarily() -> None:
    snapshot = _snapshot()
    snapshot = replace(
        snapshot, tracks=(*snapshot.tracks, replace(snapshot.tracks[0], track_id=10))
    )
    result = project_genius_browse(snapshot, (_sidecar(),))
    assert not result.collections
    assert result.issues[0].code == "genius.ambiguous_track"


def test_unsupported_and_malformed_sources_do_not_hide_other_valid_collections() -> (
    None
):
    sidecars = (
        _sidecar(),
        PlaybackSidecar("GeniusPlaylist_2.plist", plistlib.dumps({"version": 12})),
        PlaybackSidecar("GeniusPlaylist_3.plist", b"malformed"),
        PlaybackSidecar("Play Counts", b"not a Genius document"),
    )
    result = project_genius_browse(_snapshot(), sidecars, sqlite_library=b"bad SQLite")
    assert len(result.collections) == 1
    assert {issue.code for issue in result.issues} == {
        "genius.unsupported_playlist",
        "genius.invalid_playlist",
        "genius.invalid_sqlite",
    }


def test_duplicate_saved_filenames_or_native_collection_ids_are_ambiguous() -> None:
    repeated = project_genius_browse(
        _snapshot(), (_sidecar(), _sidecar(name="geniusplaylist_1.plist"))
    )
    assert not repeated.collections
    assert all(issue.code == "genius.duplicate_source" for issue in repeated.issues)
    playlist = replace(_playlist(), playlist_persistent_id=100)
    duplicate_id = project_genius_browse(
        _snapshot(), (_sidecar(playlist), _sidecar(playlist, "GeniusPlaylist_2.plist"))
    )
    assert not duplicate_id.collections
    assert duplicate_id.issues[0].code == "genius.duplicate_collection"


@pytest.mark.parametrize(
    "sql,code",
    [
        (
            "UPDATE item_to_container SET item_pid=999 WHERE container_pid=100 AND physical_order=1",
            "genius.missing_track",
        ),
        (
            "UPDATE item_to_container SET physical_order=0 WHERE container_pid=100",
            "genius.invalid_mix",
        ),
        (
            "UPDATE item_to_container SET physical_order=-1 WHERE container_pid=100 AND physical_order=1",
            "genius.invalid_mix",
        ),
        ("UPDATE container SET name=X'0102' WHERE pid=100", "genius.invalid_mix"),
    ],
)
def test_one_malformed_mix_does_not_hide_other_mixes(sql: str, code: str) -> None:
    result = project_genius_browse(_snapshot(), sqlite_library=_sqlite(sql))
    assert tuple(
        collection.native_playlist_id for collection in result.collections
    ) == (101,)
    assert result.issues[0].code == code


def test_mix_without_compatibility_table_remains_browsable() -> None:
    result = project_genius_browse(
        _snapshot(), sqlite_library=_sqlite("DROP TABLE container_seed")
    )
    assert len(result.collections) == 2
    assert all(collection.seed_track_id is None for collection in result.collections)
    assert not result.issues


@pytest.mark.parametrize("first_seed", [-11, 999])
def test_multiple_compatibility_seeds_do_not_claim_a_single_playback_seed(
    first_seed: int,
) -> None:
    result = project_genius_browse(
        _snapshot(),
        sqlite_library=_sqlite(
            f"UPDATE container_seed SET item_pid={first_seed};"
            "INSERT INTO container_seed VALUES (100,33,1)"
        ),
    )
    assert len(result.collections) == 2
    assert result.collections[1].seed_track_id is None
    assert result.issues[0].code == "genius.multiple_mix_seeds"


@pytest.mark.parametrize(
    "seed,code", [(999, "genius.missing_track"), (0, "genius.invalid_identity")]
)
def test_invalid_optional_seed_does_not_hide_known_mix_starting_tracks(
    seed: int, code: str
) -> None:
    result = project_genius_browse(
        _snapshot(),
        sqlite_library=_sqlite(f"UPDATE container_seed SET item_pid={seed}"),
    )
    assert len(result.collections) == 2
    assert result.collections[1].track_ids == (9, 7, 9)
    assert result.collections[1].seed_track_id is None
    assert result.issues[0].code == code


def test_no_sources_returns_empty_browse() -> None:
    assert project_genius_browse(_snapshot()) == GeniusBrowse()


def _canonical_snapshot(seed: int | None = _HIGH_PID) -> LibrarySnapshot:
    return replace(
        _snapshot(),
        playlists=(
            Playlist(
                99,
                "Saved Genius",
                PlaylistKind.GENIUS,
                entries=playlist_entries((7, 9, 7)),
                genius_seed_persistent_id=seed,
            ),
            Playlist(100, "Ordinary", entries=playlist_entries((8,))),
        ),
    )


def test_canonical_genius_playlist_is_browsable_without_companion_files() -> None:
    snapshot = _canonical_snapshot()
    before = replace(snapshot)
    result = project_genius_browse(snapshot)
    assert not result.issues
    assert len(result.collections) == 1
    collection = result.collections[0]
    assert collection.kind is GeniusCollectionKind.PLAYLIST
    assert collection.track_ids == (7, 9, 7)
    assert collection.seed_track_id == 7
    assert collection.native_playlist_id == 99
    assert collection.collection_id == "genius-playlist:0000000000000063"
    assert snapshot == before


def test_same_native_identity_deduplicates_canonical_playlist_and_saved_sidecar() -> (
    None
):
    saved = replace(_playlist(), playlist_persistent_id=99)
    result = project_genius_browse(_canonical_snapshot(), (_sidecar(saved),))
    assert len(result.collections) == 1
    assert not result.issues
    changed = replace(saved, name="Stale name")
    result = project_genius_browse(_canonical_snapshot(), (_sidecar(changed),))
    assert len(result.collections) == 1
    assert result.collections[0].name == "Saved Genius"
    assert result.issues[0].code == "genius.playlist_shadowed"


def test_matching_content_without_native_identity_does_not_merge_collections() -> None:
    result = project_genius_browse(_canonical_snapshot(), (_sidecar(),))
    assert len(result.collections) == 2
    assert not result.issues
    assert result.collections[0].collection_id != result.collections[1].collection_id


@pytest.mark.parametrize(
    "seed,code", [(None, "genius.unavailable_seed"), (999, "genius.missing_track")]
)
def test_canonical_membership_stays_browsable_when_native_seed_is_unavailable(
    seed: int | None, code: str
) -> None:
    result = project_genius_browse(_canonical_snapshot(seed))
    assert len(result.collections) == 1
    assert result.collections[0].seed_track_id is None
    assert result.collections[0].track_ids == (7, 9, 7)
    assert result.issues[0].code == code


def test_canonical_collection_with_missing_member_is_not_partially_displayed() -> None:
    snapshot = _canonical_snapshot()
    snapshot = replace(snapshot, tracks=snapshot.tracks[:2])
    result = project_genius_browse(snapshot)
    assert not result.collections
    assert result.issues[0].code == "genius.missing_track"
