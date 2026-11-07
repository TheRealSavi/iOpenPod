"""Acoustic features and bounded native Genius relationships."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from iOpenPod.app import genius_audio
from iOpenPod.app.genius_audio import (
    GENIUS_AUDIO_FEATURE_COUNT,
    GeniusAudioProfile,
    profile_genius_pcm,
    rank_genius_candidates,
)


def _features(value: float) -> tuple[float, ...]:
    return (value, *(0.0 for _ in range(28)))


def _profile(
    body: float, *, intro: float | None = None, outro: float | None = None
) -> GeniusAudioProfile:
    return GeniusAudioProfile(
        180.0,
        None if intro is None else _features(intro),
        _features(body),
        None if outro is None else _features(outro),
    )


def _tone(frequency: float, seconds: float, sample_rate: int = 22050) -> bytes:
    times = np.arange(round(seconds * sample_rate), dtype=np.float64) / sample_rate
    return (0.5 * np.sin(2 * np.pi * frequency * times)).astype("<f4").tobytes()


def test_silence_and_single_sample_are_finite() -> None:
    silence = profile_genius_pcm(bytes(22050 * 4))
    assert silence == GeniusAudioProfile(1.0, None, (0.0,) * 29, None)
    single = profile_genius_pcm(np.asarray([0.25], dtype="<f4").tobytes())
    assert single.duration_seconds == 1 / 22050
    assert single.intro is None and single.outro is None
    assert len(single.body) == GENIUS_AUDIO_FEATURE_COUNT
    assert all(math.isfinite(value) for value in single.body)


@pytest.mark.parametrize("seconds", [1, 40])
def test_short_tracks_have_only_whole_body(seconds: int) -> None:
    profile = profile_genius_pcm(bytes(seconds * 22050 * 4))
    assert profile.duration_seconds == seconds
    assert profile.intro is None and profile.outro is None
    assert profile.body == (0.0,) * 29


def test_long_track_profiles_distinct_twenty_second_ends() -> None:
    profile = profile_genius_pcm(_tone(220, 20) + _tone(880, 5) + _tone(1760, 20))
    assert profile.duration_seconds == 45
    assert profile.intro is not None and profile.outro is not None
    for segment, frequency in (
        (profile.intro, 220),
        (profile.body, 880),
        (profile.outro, 1760),
    ):
        assert len(segment) == 29
        assert all(math.isfinite(value) for value in segment)
        assert segment[1] == pytest.approx(frequency, rel=0.03)
        assert segment[2] >= 0
        assert all(value >= 0 for value in segment[16:])
    assert profile.intro[3:16] != profile.body[3:16]


def test_periodic_clicks_have_measured_tempo() -> None:
    sample_rate = 22050
    samples = np.zeros(8 * sample_rate, dtype=np.float32)
    pulse = np.hanning(220).astype(np.float32)
    for start in range(0, len(samples) - len(pulse), sample_rate // 2):
        samples[start : start + len(pulse)] = pulse
    profile = profile_genius_pcm(samples.astype("<f4").tobytes())
    assert profile.body[0] == pytest.approx(120, abs=5)


def test_block_boundaries_preserve_whole_segment_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quiet = np.frombuffer(_tone(880, 1), dtype="<f4") * 1e-5
    pcm = _tone(220, 1) + quiet.astype("<f4").tobytes() + _tone(1760, 1)
    whole = profile_genius_pcm(pcm)
    monkeypatch.setattr("iOpenPod.app.genius_audio._BLOCK_FRAMES", 7)
    blocked = profile_genius_pcm(pcm)
    assert blocked.body == pytest.approx(whole.body, rel=1e-10, abs=1e-8)


@pytest.mark.parametrize("block_size", [7, 256, 1024])
@pytest.mark.parametrize("sample_rate", [22050, 16000])
def test_bounded_tempo_matches_whole_segment_estimator(
    monkeypatch: pytest.MonkeyPatch, block_size: int, sample_rate: int
) -> None:
    import librosa

    onset = np.zeros(1703, dtype=np.float64)
    onset[::21] = 1.0
    onset[700::17] += 0.7
    expected = librosa.feature.tempo(
        onset_envelope=onset, sr=sample_rate, hop_length=512
    )
    monkeypatch.setattr(genius_audio, "_TEMPO_BLOCK_FRAMES", block_size)
    # Compare the bounded estimator directly with librosa's reference algorithm.
    actual = genius_audio._segment_tempo(onset, sample_rate, lambda: None)  # pyright: ignore[reportPrivateUsage]
    assert actual == float(expected[0])


@pytest.mark.parametrize("pcm", [b"", b"x", b"12345"])
def test_invalid_sample_framing_rejected(pcm: bytes) -> None:
    with pytest.raises(ValueError, match="float32"):
        profile_genius_pcm(pcm)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_pcm_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="nonfinite"):
        profile_genius_pcm(np.asarray([value], dtype="<f4").tobytes())


@pytest.mark.parametrize("rate", [0, -1, True])
def test_invalid_sample_rate_rejected(rate: int) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        profile_genius_pcm(bytes(4), sample_rate_hz=rate)


def test_ranking_prefers_bodies_and_has_deterministic_ties() -> None:
    profiles = {7: _profile(10), 2: _profile(1), 1: _profile(0), 3: _profile(-1)}
    ranked = rank_genius_candidates(profiles)
    assert ranked[1] == (2, 3, 7)
    assert ranked == rank_genius_candidates(dict(reversed(tuple(profiles.items()))))
    assert rank_genius_candidates(profiles, limit=1)[1] == (2,)
    assert rank_genius_candidates(profiles, limit=0) == dict.fromkeys(profiles, ())


def test_transition_winner_is_limited_to_three_nearest_bodies() -> None:
    profiles = {
        1: _profile(0, intro=0, outro=10),
        2: _profile(1, intro=0, outro=0),
        3: _profile(2, intro=1, outro=100),
        4: _profile(3, intro=9, outro=100),
        5: _profile(100, intro=10, outro=0),
    }
    ranked = rank_genius_candidates(profiles)[1]
    assert ranked == (4, 5, 3, 2)
    # The second choice still compares with seed outro=10, not selected outro=100.
    changed = {**profiles, 4: replace(profiles[4], outro=_features(-100))}
    assert rank_genius_candidates(changed)[1] == ranked


def test_intro_and_outro_use_shared_normalization() -> None:
    profiles = {
        1: _profile(0, intro=0, outro=100),
        2: _profile(1, intro=99, outro=10000),
        3: _profile(2, intro=50, outro=10000),
        4: _profile(3, intro=0, outro=10000),
    }
    assert rank_genius_candidates(profiles, limit=1)[1] == (2,)


def test_missing_end_profiles_fall_back_to_body_order() -> None:
    profiles = {
        1: _profile(0, outro=100),
        2: _profile(1),
        3: _profile(2, intro=100),
        4: _profile(3, intro=100),
    }
    assert rank_genius_candidates(profiles)[1] == (2, 3, 4)


def test_equal_transitions_keep_nearest_body_order() -> None:
    profiles = {
        1: _profile(0, intro=0, outro=0),
        2: _profile(100, intro=0, outro=0),
        3: _profile(1, intro=0, outro=0),
        4: _profile(2, intro=0, outro=0),
    }
    assert rank_genius_candidates(profiles)[1] == (3, 4, 2)


def test_large_library_is_bounded_unique_and_deterministic() -> None:
    profiles = {identity: _profile(float(identity)) for identity in range(700)}
    first = rank_genius_candidates(profiles, limit=8)
    assert first == rank_genius_candidates(
        dict(reversed(tuple(profiles.items()))), limit=8
    )
    for identity, candidates in first.items():
        assert len(candidates) == len(set(candidates)) == 8
        assert identity not in candidates
        assert all(abs(candidate - identity) <= 8 for candidate in candidates)


def test_projection_search_finds_matching_distant_track_identity() -> None:
    random = np.random.default_rng(752)
    rows = random.normal(size=(700, 29))
    rows[699] = rows[0]
    profiles = {
        identity: GeniusAudioProfile(180.0, None, tuple(map(float, row)), None)
        for identity, row in enumerate(rows)
    }
    ranked = rank_genius_candidates(profiles, limit=3)
    assert ranked[0][0] == 699
    assert ranked[699][0] == 0


@pytest.mark.parametrize("limit", [-1, 257, True])
def test_invalid_limit_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        rank_genius_candidates({}, limit=limit)


@pytest.mark.parametrize(
    "profile",
    [
        _profile(math.nan),
        _profile(0, intro=math.inf),
        replace(_profile(0), body=(0.0,)),
        replace(_profile(0), duration_seconds=0),
        replace(_profile(0), duration_seconds=math.inf),
    ],
)
def test_invalid_profiles_rejected(profile: GeniusAudioProfile) -> None:
    with pytest.raises(ValueError):
        rank_genius_candidates({1: profile})


def test_empty_and_single_profile_have_no_neighbors() -> None:
    assert rank_genius_candidates({}) == {}
    assert rank_genius_candidates({9: _profile(1)}) == {9: ()}


def test_large_finite_features_normalize_without_overflow() -> None:
    ranked = rank_genius_candidates({1: _profile(1e308), 2: _profile(-1e308)})
    assert ranked == {1: (2,), 2: (1,)}


def test_profiling_and_ranking_propagate_cancellation() -> None:
    class CancelledError(Exception):
        pass

    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise CancelledError

    with pytest.raises(CancelledError):
        profile_genius_pcm(bytes(45 * 22050 * 4), checkpoint=checkpoint)
    calls = 0
    with pytest.raises(CancelledError):
        rank_genius_candidates(
            {index: _profile(index) for index in range(5)}, checkpoint=checkpoint
        )


def test_ranking_checks_cancellation_while_ordering_candidates() -> None:
    class CancelledError(Exception):
        pass

    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 12:
            raise CancelledError

    with pytest.raises(CancelledError):
        rank_genius_candidates(
            {index: _profile(index) for index in range(8)}, checkpoint=checkpoint
        )


def test_profiling_checks_cancellation_between_spectral_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancelledError(Exception):
        pass

    monkeypatch.setattr("iOpenPod.app.genius_audio._BLOCK_FRAMES", 7)
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise CancelledError

    with pytest.raises(CancelledError):
        profile_genius_pcm(_tone(220, 3), checkpoint=checkpoint)
