"""Basic native Genius policy, stable identity, and bounded graph coverage."""

from dataclasses import replace

import pytest

from iOpenPod.app import genius_generation
from iOpenPod.app.genius_generation import (
    MAX_GENIUS_CANDIDATES,
    generate_genius_update,
)
from iPodDB.genius import (
    GeniusMetadata,
    GeniusSimilarities,
    make_no_rule_genius_config,
    serialize_genius_config,
    serialize_genius_metadata,
    serialize_genius_similarities,
)
from iPodDB.library import (
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
)
from iPodDB.library.genius import (
    GeniusDatabase,
    GeniusUpdate,
    parse_genius_database,
    serialize_genius_database,
)


def _track(track_id: int, *, genius_id: int = 0, persistent_id: int = 0) -> Track:
    return Track(
        track_id,
        f"Song {track_id}",
        "",
        "",
        180_000,
        ipod=IPodTrackDetails(db_track_id=persistent_id, genius_id=genius_id),
    )


def _assignments(update: GeniusUpdate) -> dict[int, int]:
    return {track.track_id: track.genius_id for track in update.tracks}


def _candidates(update: GeniusUpdate) -> dict[int, tuple[int, ...]]:
    tracks = {track.genius_id: track.track_id for track in update.tracks}
    result: dict[int, tuple[int, ...]] = {}
    for row in update.data.similarities:
        assert isinstance(row.payload, GeniusSimilarities)
        result[tracks[row.genius_id]] = tuple(
            tracks[gid] for gid in row.payload.candidates
        )
    return result


@pytest.mark.parametrize("size", [0, 1, 2, 9, 10, 25])
def test_small_libraries_have_complete_graphs_without_claiming_native_success(
    size: int,
) -> None:
    snapshot = LibrarySnapshot(tuple(_track(index) for index in range(1, size + 1)))

    update = generate_genius_update(snapshot)

    assert update.mixes is None
    ids = _assignments(update)
    assert set(ids) == set(range(1, size + 1))
    assert len(set(ids.values())) == size
    assert all(0 < gid < 1 << 64 for gid in ids.values())
    assert set(_candidates(update)) == set(ids)
    for track_id, candidates in _candidates(update).items():
        assert set(candidates) == set(ids) - {track_id}
        assert len(candidates) == size - 1
    (config,) = update.data.configs
    assert (config.row_id, config.version) == (1, 2)
    assert (config.default_num_results, config.min_num_results) == (25, 10)
    assert config.payload is not None
    assert config.payload == make_no_rule_genius_config()
    assert len(serialize_genius_config(config.payload)) == 48
    for row in update.data.metadata:
        assert isinstance(row.payload, GeniusMetadata)
        assert row.payload.keys == (1, row.genius_id, row.genius_id, row.genius_id)
        assert len(serialize_genius_metadata(row.payload)) == 32


def test_same_snapshot_and_reordering_produce_the_same_complete_update() -> None:
    tracks = (
        replace(_track(-6), artist="Radiohead", genre="Rock", album="OK Computer"),
        replace(_track(2, persistent_id=19), artist="Radiohead", genre="Rock"),
        replace(_track(3, genius_id=500), artist="Bowie", genre="Rock"),
        _track(-4),
    )
    snapshot = LibrarySnapshot(tracks)
    expected = generate_genius_update(snapshot)

    assert generate_genius_update(snapshot) == expected
    assert generate_genius_update(replace(snapshot, tracks=tracks[::-1])) == expected
    assert _assignments(expected)[3] == 500
    assert snapshot.tracks == tracks
    assert snapshot.tracks[0].ipod is not None
    assert snapshot.tracks[0].ipod.genius_id == 0


def test_persistent_identity_stabilizes_new_ids_across_semantic_id_and_tag_changes() -> (
    None
):
    track = _track(1, persistent_id=900)
    initial = generate_genius_update(LibrarySnapshot((track,)))
    changed = generate_genius_update(
        LibrarySnapshot(
            (replace(track, track_id=55, artist="Different", album="Retagged"),)
        )
    )

    assert _assignments(initial)[1] == _assignments(changed)[55]


def test_persisted_assignments_survive_temporary_track_id_replacement_and_new_tracks() -> (
    None
):
    first = generate_genius_update(LibrarySnapshot((_track(-1), _track(-2))))
    ids = _assignments(first)
    reloaded = LibrarySnapshot(
        (
            _track(800, persistent_id=1200, genius_id=ids[-1]),
            _track(801, persistent_id=1201, genius_id=ids[-2]),
            _track(-3),
        )
    )

    next_ids = _assignments(generate_genius_update(reloaded))

    assert next_ids[800] == ids[-1]
    assert next_ids[801] == ids[-2]
    assert next_ids[-3] not in ids.values()


def test_collisions_and_duplicate_existing_ids_allocate_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    largest = (1 << 64) - 1

    def colliding_id(_track: Track) -> int:
        return largest

    monkeypatch.setattr(genius_generation, "_initial_genius_id", colliding_id)
    tracks = (
        _track(1),
        _track(2, genius_id=55),
        _track(3, genius_id=55),
        _track(4, genius_id=42),
        _track(5, genius_id=largest),
    )

    update = generate_genius_update(LibrarySnapshot(tracks))
    ids = _assignments(update)

    assert ids[4] == 42
    assert ids[5] == largest
    assert 55 not in ids.values()
    assert len(set(ids.values())) == len(tracks)
    assert all(0 < gid < 1 << 64 for gid in ids.values())
    assert generate_genius_update(LibrarySnapshot(tracks[::-1])) == update


@pytest.mark.parametrize("invalid", [-1, 0, 1 << 64, True])
def test_invalid_existing_genius_ids_are_replaced(invalid: int) -> None:
    update = generate_genius_update(LibrarySnapshot((_track(1, genius_id=invalid),)))

    (assignment,) = update.tracks
    assert type(assignment.genius_id) is int
    assert 0 < assignment.genius_id < 1 << 64
    assert assignment.genius_id != invalid


@pytest.mark.parametrize(
    "media_type",
    [
        MediaType.PODCAST,
        MediaType.VIDEO_PODCAST,
        MediaType.AUDIOBOOK,
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
    ],
)
def test_non_music_tracks_are_excluded_from_ids_metadata_and_relationships(
    media_type: MediaType,
) -> None:
    snapshot = LibrarySnapshot(
        (
            _track(1),
            replace(_track(2, genius_id=500), media_types=(media_type,)),
            replace(_track(3), metadata=TrackMetadata(podcast=True)),
            _track(4),
        )
    )

    update = generate_genius_update(snapshot)

    assert set(_assignments(update)) == {1, 4}
    assert _candidates(update) == {1: (4,), 4: (1,)}
    assert {row.genius_id for row in update.data.metadata} == set(
        _assignments(update).values()
    )


def test_metadata_matches_rank_before_unrelated_fallback_tracks() -> None:
    tracks = (
        replace(_track(1), artist="Artist A", album="Album", genre="Rock"),
        replace(_track(2), artist="Unrelated", genre="Jazz"),
        replace(_track(3), artist=" artist a ", album="Other", genre="Classical"),
        replace(_track(4), artist="Artist B", genre=" rock "),
        replace(_track(5), artist="Artist C", album_artist="ARTIST A", album="ALBUM"),
        _track(6),
    )

    candidates = _candidates(generate_genius_update(LibrarySnapshot(tracks)))[1]

    assert candidates[:3] == (3, 4, 5)
    assert set(candidates[3:]) == {2, 6}
    # Different artists and albums are represented without firmware spacing rules.
    assert len({tracks[track_id - 1].artist for track_id in candidates[:3]}) == 3


def test_large_homogeneous_library_has_bounded_unique_candidates_and_global_reach() -> (
    None
):
    size = MAX_GENIUS_CANDIDATES * 4
    tracks = tuple(
        replace(
            _track(index),
            artist=f"Artist {index // 350}",
            album="Album",
            genre="Rock",
        )
        for index in range(1, size + 1)
    )

    update = generate_genius_update(LibrarySnapshot(tracks))
    graph = _candidates(update)
    for track_id, candidates in graph.items():
        assert len(candidates) == MAX_GENIUS_CANDIDATES
        assert len(set(candidates)) == len(candidates)
        assert track_id not in candidates
        assert set(candidates) <= graph.keys()
        assert track_id % size + 1 in candidates
    visited = {1}
    pending = [1]
    while pending:
        for candidate in graph[pending.pop()]:
            if candidate not in visited:
                visited.add(candidate)
                pending.append(candidate)
    assert visited == graph.keys()
    assert sum(
        len(serialize_genius_similarities(row.payload))
        for row in update.data.similarities
        if row.payload is not None
    ) == size * (12 + 8 * MAX_GENIUS_CANDIDATES)


def test_generated_data_round_trips_through_the_public_database_codec() -> None:
    snapshot = LibrarySnapshot(tuple(_track(index) for index in range(-8, 12)))
    update = generate_genius_update(snapshot)

    encoded = serialize_genius_database(GeniusDatabase(update.data))

    decoded = parse_genius_database(encoded).data
    assert decoded.configs == update.data.configs
    assert {row.genius_id: row for row in decoded.metadata} == {
        row.genius_id: row for row in update.data.metadata
    }
    assert {row.genius_id: row for row in decoded.similarities} == {
        row.genius_id: row for row in update.data.similarities
    }


@pytest.mark.parametrize("cancel_after", [1, 4 * 300 + 3])
def test_cancellation_propagates_before_start_and_during_candidate_generation(
    cancel_after: int,
) -> None:
    snapshot = LibrarySnapshot(tuple(_track(index) for index in range(300)))
    calls = 0

    class CancelledError(Exception):
        pass

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == cancel_after:
            raise CancelledError

    with pytest.raises(CancelledError):
        generate_genius_update(snapshot, checkpoint=checkpoint)
    assert calls == cancel_after
