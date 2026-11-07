"""Manual ownership and automatic rotation share a fixed genre catalog."""

import random
from dataclasses import replace

import pytest

from iOpenPod.app.genius_mixes import (
    MIX_CATALOG,
    ManagedMix,
    MixPolicy,
    MixState,
    plan_mixes,
    propose_mixes,
)
from iOpenPod.app.services.genius_mixes import decode_mix_state, encode_mix_state
from iPodDB.library import LibrarySnapshot, MediaType, Track
from iPodDB.library.genius import GeniusBrowse, GeniusCollection, GeniusCollectionKind


def music(*genres: str) -> LibrarySnapshot:
    return LibrarySnapshot(
        tuple(
            Track(
                genre_index * 10 + index + 1,
                f"Song {index}",
                "Artist",
                "Album",
                120_000,
                genre=genre,
            )
            for genre_index, genre in enumerate(genres)
            for index in range(10)
        )
    )


def browse(state: MixState) -> GeniusBrowse:
    return GeniusBrowse(
        tuple(
            GeniusCollection(
                f"genius-mix:{entry.container_id:016x}",
                entry.definition_key,
                GeniusCollectionKind.MIX,
                (),
                None,
                entry.container_id,
            )
            for entry in state.entries
        )
    )


def test_catalog_uses_normalized_genres_and_excludes_nonmusic() -> None:
    snapshot = music("HIP-HOP", "Alternative Rock", "Undefined genre")
    podcast = replace(
        snapshot.tracks[0], track_id=100, media_types=(MediaType.PODCAST,)
    )
    video = replace(
        snapshot.tracks[0], track_id=101, media_types=(MediaType.MUSIC_VIDEO,)
    )
    proposals = {
        p.definition.key: p
        for p in propose_mixes(
            replace(snapshot, tracks=(*snapshot.tracks, podcast, video))
        )
    }
    assert proposals["hip-hop"].track_ids == tuple(range(1, 11))
    assert proposals["alternative"].track_ids == tuple(range(11, 21))
    assert not proposals["rock"].eligible
    assert not any(p.definition.key == "undefined-genre" for p in proposals.values())


def test_manual_mixes_never_expire_and_do_not_use_automatic_slots() -> None:
    snapshot = music("Rock", "Pop", "Jazz")
    first = plan_mixes(
        snapshot,
        GeniusBrowse(),
        MixState(),
        manual_keys=("rock", "rock"),
        policy=MixPolicy(1, 1),
        now=100,
        rng=random.Random(2),
    )
    assert len(first.additions) == 2
    manual = next(entry for entry in first.state.entries if entry.added_at is None)
    automatic = next(
        entry for entry in first.state.entries if entry.added_at is not None
    )
    second = plan_mixes(
        snapshot,
        browse(first.state),
        first.state,
        policy=MixPolicy(1, 1),
        now=100 + 86401,
        rng=random.Random(2),
    )
    assert manual in second.state.entries
    assert second.removals == (automatic.container_id,)
    assert second.additions[0].name != first.additions[1].name
    assert len(second.state.entries) == 2


def test_explicit_removal_can_delete_one_unowned_native_mix() -> None:
    state = MixState((ManagedMix(7, "rock"),))
    native = GeniusBrowse(
        (
            *browse(state).collections,
            GeniusCollection(
                "genius-mix:0000000000000008",
                "Other Mix",
                GeniusCollectionKind.MIX,
                (),
                None,
                8,
            ),
        )
    )
    plan = plan_mixes(music("Rock"), native, state, remove_ids=(8,), now=100)
    assert plan.removals == (8,)
    assert plan.state == state
    assert not plan.additions


def test_expiry_is_strict_and_no_alternative_keeps_original_age() -> None:
    state = MixState((ManagedMix(7, "rock", 100),))
    for now in (50, 86500, 86501):
        plan = plan_mixes(
            music("Rock"), browse(state), state, policy=MixPolicy(1, 1), now=now
        )
        assert plan.state == state
        assert not plan.removals and not plan.additions
    plan = plan_mixes(
        music("Rock", "Jazz"), browse(state), state, policy=MixPolicy(1, 1), now=86500
    )
    assert not plan.removals
    plan = plan_mixes(
        music("Rock", "Jazz"), browse(state), state, policy=MixPolicy(1, 1), now=86501
    )
    assert plan.removals == (7,)
    assert plan.state.entries[0].definition_key == "jazz"
    assert plan.state.entries[0].added_at == 86501


def test_manual_selection_converts_automatic_ownership_without_replacing_native_mix() -> (
    None
):
    state = MixState((ManagedMix(7, "rock", 100),))
    plan = plan_mixes(
        music("Rock", "Jazz"), browse(state), state, manual_keys=("rock",), now=1000
    )
    assert plan.state == MixState((ManagedMix(7, "rock"),))
    assert not plan.removals and not plan.additions


def test_count_reduction_removes_only_owned_automatic_mixes() -> None:
    state = MixState(
        (ManagedMix(7, "rock", 100), ManagedMix(8, "pop", 200), ManagedMix(9, "jazz"))
    )
    external = GeniusCollection(
        "external", "From iTunes", GeniusCollectionKind.MIX, (), None, 77
    )
    native = replace(browse(state), collections=(*browse(state).collections, external))
    plan = plan_mixes(
        music("Rock", "Pop", "Jazz"), native, state, policy=MixPolicy(1, 30), now=300
    )
    assert plan.removals == (7,)
    plan = plan_mixes(
        music("Rock", "Pop", "Jazz"), native, state, policy=MixPolicy(0, 30), now=300
    )
    assert plan.removals == (7, 8)
    assert plan.state.entries == (ManagedMix(9, "jazz"),)


def test_automatic_fill_is_unique_and_bounded_by_eligible_catalog() -> None:
    plan = plan_mixes(
        music("Rock", "Jazz"),
        GeniusBrowse(),
        MixState(),
        policy=MixPolicy(18, 30),
        now=10,
    )
    assert len(plan.additions) == 2
    assert len({entry.definition_key for entry in plan.state.entries}) == 2
    assert len({entry.container_id for entry in plan.state.entries}) == 2
    repeated = plan_mixes(
        music("Rock", "Jazz"),
        browse(plan.state),
        plan.state,
        policy=MixPolicy(18, 30),
        now=11,
    )
    assert not repeated.additions and not repeated.removals


def test_missing_external_mix_drops_stale_ownership_without_deleting_anything() -> None:
    state = MixState((ManagedMix(7, "rock", 100),))
    plan = plan_mixes(music("Rock"), GeniusBrowse(), state, policy=MixPolicy(), now=200)
    assert not plan.removals and not plan.state.entries


def test_ineligible_manual_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="enough matching music"):
        plan_mixes(
            music("Rock"), GeniusBrowse(), MixState(), manual_keys=("jazz",), now=10
        )


def test_ownership_document_round_trip_and_validation() -> None:
    state = MixState((ManagedMix(7, "rock"), ManagedMix(8, "jazz", 123)))
    assert decode_mix_state(encode_mix_state(state)) == state
    for data in (
        b'{"version":2,"mixes":[]}',
        b'{"version":1,"mixes":[{"container_id":7,"definition":"rock"}]}',
        b'{"version":1,"mixes":[{"container_id":true,"definition":"rock","added_at":1}]}',
        encode_mix_state(MixState((ManagedMix(7, "rock"), ManagedMix(7, "jazz")))),
    ):
        with pytest.raises(ValueError):
            decode_mix_state(data)


@pytest.mark.parametrize(
    "count,days", [(-1, 30), (len(MIX_CATALOG) + 1, 30), (1, 0), (True, 1)]
)
def test_invalid_policy_is_rejected(count: int, days: int) -> None:
    with pytest.raises(ValueError):
        MixPolicy(count, days)
