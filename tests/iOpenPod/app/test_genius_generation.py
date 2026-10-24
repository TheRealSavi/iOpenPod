"""Native Genius ranking, semantic spacing keys, identity, and graph coverage."""

import struct
from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

from iOpenPod.app import genius_generation
from iOpenPod.app.genius_audio import GeniusAudioProfile
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
    GeniusConfig,
    GeniusDatabase,
    GeniusSpacingRule,
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


def _metadata(update: GeniusUpdate) -> dict[int, tuple[int, ...]]:
    tracks = {track.genius_id: track.track_id for track in update.tracks}
    result: dict[int, tuple[int, ...]] = {}
    for row in update.data.metadata:
        assert isinstance(row.payload, GeniusMetadata)
        result[tracks[row.genius_id]] = row.payload.keys
    return result


def _profile(tempo: float) -> GeniusAudioProfile:
    return GeniusAudioProfile(180.0, None, (tempo, *([0.0] * 28)), None)


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
    assert isinstance(config.payload, GeniusConfig)
    assert config.payload.entries == (
        GeniusSpacingRule(1, 1, 6, 2),
        GeniusSpacingRule(2, 1, 10, 2),
    )
    expected_config = (
        struct.pack("<I", 2)
        + struct.pack("<5I", 3, 1, 1, 6, 2)
        + struct.pack("<5I", 3, 2, 1, 10, 2)
        + make_no_rule_genius_config().control_tail
    )
    assert serialize_genius_config(config.payload) == expected_config
    assert len(expected_config) == 88
    for row in update.data.metadata:
        assert isinstance(row.payload, GeniusMetadata)
        assert row.payload.keys[0] == 1
        assert row.payload.keys[3] == row.genius_id
        assert all(0 < key < 1 << 64 for key in row.payload.keys)
        assert len(serialize_genius_metadata(row.payload)) == 32
    assert len({keys[1] for keys in _metadata(update).values()}) == size
    assert len({keys[2] for keys in _metadata(update).values()}) == size


def test_homogeneous_spacing_can_relax_to_the_first_use_counter() -> None:
    snapshot = LibrarySnapshot(
        tuple(
            replace(_track(index), artist="Only Artist", album="Only Album")
            for index in range(1, 31)
        )
    )
    update = generate_genius_update(snapshot)
    keys = _metadata(update)
    config = update.data.configs[0].payload
    assert isinstance(config, GeniusConfig)
    assert len(config.entries) == 2
    # Upstream FORMAT §4 / genius_sim.Distance.consume inserts a first-used key
    # with counter 1. With no other group to accept, that counter cannot grow.
    # This checks the documented state model, not complete firmware playback.
    first_use_counter = 1
    for rule in config.entries:
        assert isinstance(rule, GeniusSpacingRule)
        assert len({value[rule.field_index] for value in keys.values()}) == 1
        assert first_use_counter < rule.distance
        assert rule.floor == 1
        effective_distance = rule.distance + rule.jitter
        while effective_distance > rule.floor:
            effective_distance -= 1
        assert first_use_counter >= effective_distance


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
    assert generate_genius_update(snapshot, profiles={}) == expected
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
        replace(_track(3), artist="Artist A", album="Other", genre="Classical"),
        replace(_track(4), artist="Artist B", genre=" rock "),
        replace(_track(5), artist="Artist C", album_artist="Artist A", album="ALBUM"),
        _track(6),
    )

    candidates = _candidates(generate_genius_update(LibrarySnapshot(tracks)))[1]

    assert candidates[:3] == (3, 4, 5)
    assert set(candidates[3:]) == {2, 6}
    # Candidate ranking and native spacing use the same artist and album groups.
    assert len({tracks[track_id - 1].artist for track_id in candidates[:3]}) == 3


def test_artist_and_album_keys_follow_exact_artist_and_common_album_identity() -> None:
    tracks = (
        replace(_track(1), artist="Björk", album="Debut"),
        replace(_track(2), artist="Björk", album="DEBUT"),
        replace(_track(3), artist="Björk", album="Post"),
        replace(_track(4), artist="Another", album="Debut"),
        replace(
            _track(5), artist="Singer A", album_artist="Various Artists", album="Hits"
        ),
        replace(
            _track(6),
            artist="Singer B",
            album_artist="Various Artists",
            album="HITS",
        ),
        replace(_track(7), artist="Artist", album="Part Album"),
        replace(_track(8), artist="Artist Part", album="Album"),
        replace(_track(9), artist="BJÖRK", album="Debut"),
        replace(_track(10), artist="Björk ", album="Debut"),
        replace(_track(11), artist="Björk", album=" Debut "),
        replace(
            _track(12), artist="Singer C", album_artist="various artists", album="Hits"
        ),
    )

    original = generate_genius_update(LibrarySnapshot(tracks))
    keys = _metadata(original)

    assert keys[1][1:3] == keys[2][1:3]
    assert keys[1][1] == keys[3][1]
    assert keys[1][2] != keys[3][2]
    assert keys[1][2] != keys[4][2]
    assert keys[5][1] != keys[6][1]
    assert keys[5][2] == keys[6][2]
    assert keys[7][2] != keys[8][2]
    assert keys[1][1] != keys[9][1]
    assert keys[1][2] != keys[9][2]
    assert keys[1][1] != keys[10][1]
    assert keys[1][2] != keys[10][2]
    assert keys[1][2] != keys[11][2]
    assert keys[5][2] != keys[12][2]
    later = _metadata(
        generate_genius_update(LibrarySnapshot((_track(-9), *tracks[::-1])))
    )
    assert {track_id: later[track_id] for track_id in keys} == keys


def test_incomplete_tags_have_independent_keys_stable_after_id_reload() -> None:
    tracks = (
        _track(-1),
        _track(-2),
        replace(_track(-3), artist="Known"),
        replace(_track(-4), artist="Known"),
        replace(_track(-5), album="Untitled"),
        replace(_track(-6), album="Untitled"),
        replace(_track(-7), artist=" \t", album=" \n"),
        replace(_track(-8), artist=" \t", album=" \n"),
    )
    update = generate_genius_update(LibrarySnapshot(tracks))
    keys = _metadata(update)

    assert keys[-1][1] != keys[-2][1]
    assert keys[-3][1] == keys[-4][1]
    assert keys[-5][1] != keys[-6][1]
    assert keys[-7][1] != keys[-8][1]
    assert len({row[2] for row in keys.values()}) == len(tracks)
    reloaded = _track(55, persistent_id=800, genius_id=_assignments(update)[-1])
    assert (
        _metadata(generate_genius_update(LibrarySnapshot((reloaded,))))[55] == keys[-1]
    )


def test_audio_rankings_override_metadata_and_fill_missing_profiles() -> None:
    tracks = (
        replace(_track(1), artist="Artist A"),
        replace(_track(2), artist="Artist A"),
        replace(_track(3), artist="Unrelated"),
        _track(4),
    )
    profiles = {1: _profile(120.0), 2: _profile(200.0), 3: _profile(121.0)}

    update = generate_genius_update(LibrarySnapshot(tracks), profiles=profiles)
    graph = _candidates(update)

    assert graph[1] == (3, 2, 4)
    assert set(graph[4]) == {1, 2, 3}
    assert update.mixes is None
    assert update == generate_genius_update(
        LibrarySnapshot(tracks[::-1]), profiles=dict(reversed(tuple(profiles.items())))
    )
    no_audio = generate_genius_update(LibrarySnapshot(tracks))
    assert update.tracks == no_audio.tracks
    assert update.data.metadata == no_audio.data.metadata
    assert update.data.configs == no_audio.data.configs


def test_ranking_receives_only_eligible_profiles_and_the_candidate_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(120.0)
    observed: list[int] = []

    def rank(
        profiles: Mapping[int, GeniusAudioProfile],
        *,
        limit: int,
        checkpoint: Callable[[], None] | None = None,
    ) -> dict[int, tuple[int, ...]]:
        assert dict(profiles) == {1: profile, 3: profile}
        assert limit == MAX_GENIUS_CANDIDATES
        assert checkpoint is not None
        checkpoint()
        observed.append(1)
        return {1: (3,), 3: (1,)}

    monkeypatch.setattr(genius_generation, "rank_genius_candidates", rank)
    tracks = (
        _track(1),
        replace(_track(2), media_types=(MediaType.AUDIOBOOK,)),
        _track(3),
        _track(4),
    )

    update = generate_genius_update(
        LibrarySnapshot(tracks), profiles=dict.fromkeys((1, 2, 3, 99), profile)
    )

    assert observed == [1]
    assert _candidates(update) == {1: (3, 4), 3: (1, 4), 4: (1, 3)}


def test_cancellation_propagates_from_audio_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranking = False

    class CancelledError(Exception):
        pass

    def checkpoint() -> None:
        if ranking:
            raise CancelledError

    def rank(
        _profiles: Mapping[int, GeniusAudioProfile],
        *,
        limit: int,
        checkpoint: Callable[[], None] | None = None,
    ) -> dict[int, tuple[int, ...]]:
        nonlocal ranking
        assert limit == MAX_GENIUS_CANDIDATES
        assert checkpoint is not None
        ranking = True
        checkpoint()
        pytest.fail("Cancellation must interrupt ranking.")

    monkeypatch.setattr(genius_generation, "rank_genius_candidates", rank)

    with pytest.raises(CancelledError):
        generate_genius_update(
            LibrarySnapshot((_track(1),)),
            profiles={1: _profile(120.0)},
            checkpoint=checkpoint,
        )


@pytest.mark.parametrize("with_audio", [False, True])
def test_large_homogeneous_library_has_bounded_unique_candidates_and_global_reach(
    with_audio: bool,
) -> None:
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

    profiles = (
        {track.track_id: _profile(float(track.track_id % 200)) for track in tracks}
        if with_audio
        else None
    )
    update = generate_genius_update(LibrarySnapshot(tracks), profiles=profiles)
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
