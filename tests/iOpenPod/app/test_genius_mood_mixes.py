"""Acoustic Mix proposals use verified profiles and explicit romance cues."""

import random
from dataclasses import replace

import pytest

from iOpenPod.app.genius_audio import (
    GeniusAudioCharacter,
    GeniusAudioProfile,
    GeniusVocalEvidence,
)
from iOpenPod.app.genius_mixes import MixPolicy, MixState, plan_mixes, propose_mixes
from iOpenPod.app.genius_mood import focus_candidate, mood_matches
from iPodDB.library import LibrarySnapshot, Track
from iPodDB.library.genius import GeniusBrowse


def _profile(
    tempo: float,
    centroid: float,
    texture_change: float = 0.04,
    *,
    energetic: bool = False,
) -> GeniusAudioProfile:
    body = (
        tempo,
        centroid,
        centroid * centroid * texture_change,
        *(0.0 for _ in range(26)),
    )
    character = (
        GeniusAudioCharacter(85, 0.75, 8, 0.04, 1)
        if energetic
        else GeniusAudioCharacter(20, 0.2, 4, 0.003, 1)
    )
    return GeniusAudioProfile(
        180.0, None, body, None, character, GeniusVocalEvidence("test", 0.05, 48)
    )


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
            else _profile(132, 2700, energetic=True)
            if track.track_id <= 20
            else _profile(95, 1300)
            if track.track_id <= 30
            else _profile(160, 4000, energetic=True)
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
    profiles = {index: _profile(132, 2700, energetic=True) for index in range(11, 21)}
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
    profiles = {index: _profile(132, 2700, energetic=True) for index in range(11, 20)}
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
    profiles = {index: _profile(132, 2700, energetic=True) for index in range(11, 21)}
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


@pytest.mark.parametrize(
    "fraction, expected", [(0.0, True), (0.1, True), (0.4, False), (0.9, False)]
)
def test_focus_allows_only_sparse_vocals(fraction: float, expected: bool) -> None:
    calm = replace(_profile(85, 1100), vocals=GeniusVocalEvidence("test", fraction, 48))
    assert mood_matches("focus", calm) is expected
    assert mood_matches("relax", calm)


def test_missing_vocal_evidence_does_not_mean_instrumental() -> None:
    unknown = replace(_profile(85, 1100), vocals=None)
    assert focus_candidate(unknown)
    assert not mood_matches("focus", unknown)
    assert mood_matches("relax", unknown)
    legacy = replace(unknown, character=None)
    assert not any(
        mood_matches(key, legacy) for key in ("focus", "relax", "energy", "love")
    )


def test_compressed_noisy_music_is_not_calm_just_because_it_is_steady() -> None:
    dense = replace(
        _profile(123, 2815), character=GeniusAudioCharacter(44, 0.24, 2.4, 0.063, 1)
    )
    assert not focus_candidate(dense)
    assert not mood_matches("relax", dense)
    assert mood_matches("energy", dense)


def test_fast_estimated_tempo_alone_cannot_make_energy() -> None:
    quiet = _profile(160, 1500)
    assert not mood_matches("energy", quiet)
    assert mood_matches("focus", quiet)


@pytest.mark.parametrize("tempo", [75, 150])
def test_strong_rhythm_is_energy_at_half_or_double_estimated_tempo(
    tempo: float,
) -> None:
    assert mood_matches("energy", _profile(tempo, 2700, energetic=True))
    assert not mood_matches("focus", _profile(tempo, 2700, energetic=True))


def test_abrupt_changes_exclude_focus_even_when_average_sound_is_quiet() -> None:
    changing = replace(
        _profile(85, 1100, texture_change=0.5),
        character=GeniusAudioCharacter(20, 0.2, 25, 0.003, 1),
    )
    assert not focus_candidate(changing)


def test_gentle_repeated_notes_and_melodic_changes_are_not_intense_beats() -> None:
    gentle = replace(
        _profile(140, 1100, texture_change=0.35),
        character=GeniusAudioCharacter(40, 0.67, 7, 0.003, 1),
    )
    assert focus_candidate(gentle)
    assert mood_matches("focus", gentle)
    assert not mood_matches("energy", gentle)


def test_large_confident_pool_is_not_truncated_or_filled_with_weak_matches() -> None:
    snapshot = LibrarySnapshot(
        tuple(Track(i, f"Song {i}", "Artist", "Album", 180_000) for i in range(1, 1202))
    )
    profiles = {i: _profile(85, 1100) for i in range(1, 1201)}
    profiles[1201] = _profile(132, 2700, energetic=True)
    proposals = {
        p.definition.key: p for p in propose_mixes(snapshot, profiles=profiles)
    }
    assert len(proposals["focus"].track_ids) == 1200
    assert proposals["energy"].track_ids == (1201,)
    assert not proposals["energy"].eligible
