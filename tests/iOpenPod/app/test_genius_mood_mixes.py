"""Acoustic Mix proposals use verified profiles and explicit romance cues."""

import random

import pytest

from iOpenPod.app.genius_audio import GeniusAudioProfile
from iOpenPod.app.genius_mixes import MixPolicy, MixState, plan_mixes, propose_mixes
from iPodDB.library import LibrarySnapshot, Track
from iPodDB.library.genius import GeniusBrowse


def _profile(
    tempo: float, centroid: float, texture_change: float = 0.2
) -> GeniusAudioProfile:
    body = (
        tempo,
        centroid,
        centroid * centroid * texture_change,
        *(0.0 for _ in range(26)),
    )
    return GeniusAudioProfile(180.0, None, body, None)


def _library() -> LibrarySnapshot:
    return LibrarySnapshot(
        tuple(
            Track(
                index,
                f"Love Song {index}" if index <= 10 else f"Song {index}",
                "Artist",
                "Album",
                180_000,
            )
            for index in range(1, 41)
        )
    )


def test_mood_proposals_use_audio_and_love_requires_explicit_text() -> None:
    snapshot = _library()
    profiles = {
        track.track_id: (
            _profile(85, 1100)
            if track.track_id <= 10
            else _profile(132, 2700)
            if track.track_id <= 20
            else _profile(95, 1300)
            if track.track_id <= 30
            else _profile(160, 4000)
        )
        for track in snapshot.tracks
    }
    proposals = {
        p.definition.key: p for p in propose_mixes(snapshot, profiles=profiles)
    }
    assert proposals["love"].track_ids == tuple(range(1, 11))
    assert proposals["relax"].track_ids == (*range(1, 11), *range(21, 31))
    assert proposals["energy"].track_ids == (*range(11, 21), *range(31, 41))
    assert 40 not in proposals["focus"].track_ids
    assert all(proposals[key].eligible for key in ("focus", "love", "energy", "relax"))


def test_unanalyzed_tracks_do_not_become_mood_seeds() -> None:
    snapshot = _library()
    actual = {p.definition.key: p for p in propose_mixes(snapshot)}
    preview = {p.definition.key: p for p in propose_mixes(snapshot, preview=True)}
    assert all(not actual[key].eligible for key in ("focus", "love", "energy", "relax"))
    assert preview["focus"].pending_analysis and preview["focus"].eligible
    assert preview["love"].track_ids == tuple(range(1, 11))
    assert not plan_mixes(
        snapshot, GeniusBrowse(), MixState(), policy=None, now=1
    ).additions


def test_manual_mood_mix_contains_only_analyzed_matching_seeds() -> None:
    snapshot = _library()
    profiles = {index: _profile(132, 2700) for index in range(11, 21)}
    plan = plan_mixes(
        snapshot,
        GeniusBrowse(),
        MixState(),
        manual_keys=("energy",),
        profiles=profiles,
        now=1,
    )
    assert len(plan.additions) == 1
    assert plan.additions[0].track_ids == tuple(range(11, 21))


def test_mood_mix_needs_ten_analyzed_matches() -> None:
    snapshot = _library()
    profiles = {index: _profile(132, 2700) for index in range(11, 20)}
    with pytest.raises(ValueError, match="10 analyzed"):
        plan_mixes(
            snapshot,
            GeniusBrowse(),
            MixState(),
            manual_keys=("energy",),
            profiles=profiles,
            now=1,
        )


def test_automatic_mood_mix_uses_same_analyzed_proposals() -> None:
    snapshot = _library()
    profiles = {index: _profile(132, 2700) for index in range(11, 21)}
    plan = plan_mixes(
        snapshot,
        GeniusBrowse(),
        MixState(),
        policy=MixPolicy(1, 30),
        profiles=profiles,
        now=1,
        rng=random.Random(0),
    )
    assert len(plan.additions) == 1
    assert plan.additions[0].name == "Energy Mix"
