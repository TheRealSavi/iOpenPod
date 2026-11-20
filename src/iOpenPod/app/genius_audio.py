"""Pure, bounded acoustic relationships inspired by Elephant-Ear.

The 29 features describe tempo, spectral centroid, and MFCC statistics. Ranking
adapts Elephant-Ear's two-stage choice to native Genius relationships: body
distance and outro-to-intro distance both stay anchored to the seed Track. The
firmware owns subsequent playback traversal; this module does not build a queue.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from numpy.typing import NDArray

GENIUS_AUDIO_PROFILE_VERSION = 2
GENIUS_AUDIO_FEATURE_COUNT = 29
_END_SECONDS = 20
_FRAME_SIZE = 2048
_HOP_SIZE = 512
_BLOCK_FRAMES = 1024
_TEMPO_BLOCK_FRAMES = 1024
_EXACT_NEIGHBOR_LIMIT = 512
_PROJECTION_COUNT = 8
_MAX_CANDIDATES = 256


class GeniusVocalAnalysisError(ValueError):
    """Optional source evidence was unavailable; keep the acoustic profile."""


@dataclass(frozen=True, slots=True)
class GeniusAudioCharacter:
    """Gain-independent body measurements, distinct from learned mood labels."""

    spectral_activity: float
    beat_strength: float
    dynamic_range_db: float
    spectral_flatness: float
    active_fraction: float

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.spectral_activity, math.inf),
            (self.beat_strength, 1.0),
            (self.dynamic_range_db, 60.0),
            (self.spectral_flatness, 1.0),
            (self.active_fraction, 1.0),
        ):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError("Invalid Genius audio character measurement")


@dataclass(frozen=True, slots=True)
class GeniusVocalEvidence:
    """Estimated vocal occupancy in distributed samples, not a lyric classifier."""

    provider: str
    vocal_fraction: float
    sampled_seconds: float

    def __post_init__(self) -> None:
        if (
            not self.provider
            or len(self.provider) > 1024
            or not math.isfinite(self.vocal_fraction)
            or not 0 <= self.vocal_fraction <= 1
            or not math.isfinite(self.sampled_seconds)
            or not 0 < self.sampled_seconds <= 48
        ):
            raise ValueError("Invalid Genius vocal evidence")


@dataclass(frozen=True, slots=True)
class GeniusAudioProfile:
    duration_seconds: float
    intro: tuple[float, ...] | None
    body: tuple[float, ...]
    outro: tuple[float, ...] | None
    character: GeniusAudioCharacter | None = None
    vocals: GeniusVocalEvidence | None = None


def _library_member(namespace: object, name: str) -> object:
    return getattr(namespace, name)


@dataclass(slots=True)
class _Moments:
    count: int
    mean: NDArray[np.float64]
    squared_deviations: NDArray[np.float64]

    def add(self, values: NDArray[np.float64]) -> None:
        count = values.shape[1]
        mean: NDArray[np.float64] = np.mean(values, axis=1)
        variance: NDArray[np.float64] = np.var(values, axis=1)
        total = self.count + count
        difference = mean - self.mean
        self.squared_deviations += variance * count + difference * difference * (
            self.count * count / total
        )
        self.mean += difference * (count / total)
        self.count = total

    def variance(self) -> NDArray[np.float64]:
        return self.squared_deviations / self.count


def _spectral_blocks(
    samples: NDArray[np.float32],
    sample_rate_hz: int,
    checkpoint: Callable[[], None],
) -> Iterator[tuple[NDArray[np.float64], NDArray[np.float64]]]:
    import librosa

    frames = 1 + max(samples.size, _FRAME_SIZE) // _HOP_SIZE
    half_frame = _FRAME_SIZE // 2
    for first in range(0, frames, _BLOCK_FRAMES):
        checkpoint()
        last = min(frames, first + _BLOCK_FRAMES)
        start = first * _HOP_SIZE - half_frame
        stop = (last - 1) * _HOP_SIZE + half_frame
        # These overlapping blocks reproduce one centered, zero-padded STFT;
        # internal block boundaries never introduce artificial silence.
        signal = samples[max(0, start) : min(samples.size, stop)].astype(np.float64)
        signal = np.pad(signal, (max(0, -start), max(0, stop - samples.size)))
        magnitude = np.abs(
            librosa.stft(signal, n_fft=_FRAME_SIZE, hop_length=_HOP_SIZE, center=False)
        )
        mel = librosa.feature.melspectrogram(
            S=magnitude * magnitude,
            sr=sample_rate_hz,
            n_fft=_FRAME_SIZE,
            n_mels=128,
        )
        yield magnitude, mel


def _segment_rhythm(
    onset: NDArray[np.float64],
    sample_rate_hz: int,
    checkpoint: Callable[[], None],
) -> tuple[float, float]:
    import librosa

    # Preserve librosa's whole-segment mean tempogram, without allocating its
    # autocorrelation workspace for every frame of a long Track at once.
    window = max(
        1, int(librosa.time_to_frames(8.0, sr=sample_rate_hz, hop_length=_HOP_SIZE))
    )
    padded = np.pad(onset, (window // 2, window // 2), mode="linear_ramp")
    total: NDArray[np.float64] = np.zeros(window)
    for first in range(0, onset.size, _TEMPO_BLOCK_FRAMES):
        checkpoint()
        last = min(onset.size, first + _TEMPO_BLOCK_FRAMES)
        block = librosa.feature.tempogram(
            onset_envelope=padded[first : last + window - 1],
            sr=sample_rate_hz,
            hop_length=_HOP_SIZE,
            win_length=window,
            center=False,
        )
        total += np.sum(block, axis=-1)
    checkpoint()
    average = total / onset.size
    estimated = librosa.feature.tempo(
        tg=average[:, None], sr=sample_rate_hz, hop_length=_HOP_SIZE
    )
    tempo = float(np.asarray(estimated).reshape(-1)[0])
    # Subtract the nonperiodic floor: raw autocorrelation also rewards a
    # continuously active onset envelope with no distinct pulse.
    frames_per_minute = 60 * sample_rate_hz / _HOP_SIZE
    first = max(1, round(frames_per_minute / 240))
    last = min(average.size, round(frames_per_minute / 40) + 1)
    lag = round(frames_per_minute / tempo)
    strength = 0.0
    if first < last and 0 < lag < average.size:
        floor = float(np.median(average[first:last]))
        strength = float(np.clip((average[lag] - floor) / max(1 - floor, 1e-9), 0, 1))
    return tempo, strength


def _segment_features(
    samples: NDArray[np.float32],
    sample_rate_hz: int,
    checkpoint: Callable[[], None],
) -> tuple[tuple[float, ...], GeniusAudioCharacter]:
    checkpoint()
    if not np.any(samples):
        return (0.0,) * GENIUS_AUDIO_FEATURE_COUNT, GeniusAudioCharacter(0, 0, 0, 0, 0)

    # Keep expensive analysis dependencies out of application startup.
    import librosa

    # Librosa's callable-reference overload lacks a return type. This call uses
    # only its documented array input and default scalar reference.
    power_to_db = cast(
        "Callable[[NDArray[np.float64]], NDArray[np.float64]]",
        _library_member(librosa, "power_to_db"),
    )
    centroid = _Moments(0, np.zeros(1), np.zeros(1))
    # Compute each STFT once. MFCCs need the whole-segment floor first, so keep
    # only the 128-band mel blocks, not the 1,025-bin spectra. A 15-minute
    # segment retains about 40 MB, half of its PCM; the spectra would be ~8x.
    mel_blocks: deque[NDArray[np.float64]] = deque()
    rms_blocks: list[NDArray[np.float64]] = []
    flatness_blocks: list[NDArray[np.float64]] = []
    for magnitude, mel in _spectral_blocks(samples, sample_rate_hz, checkpoint):
        centroid.add(
            librosa.feature.spectral_centroid(
                S=magnitude, sr=sample_rate_hz, n_fft=_FRAME_SIZE, hop_length=_HOP_SIZE
            )
        )
        mel_blocks.append(mel)
        rms_blocks.append(
            librosa.feature.rms(
                S=magnitude, frame_length=_FRAME_SIZE, dtype=np.float64
            )[0]
        )
        flatness_blocks.append(librosa.feature.spectral_flatness(S=magnitude)[0])
    floor: float | None = None
    frames = 1 + max(samples.size, _FRAME_SIZE) // _HOP_SIZE
    if frames > _BLOCK_FRAMES:
        # Apply one whole-segment 80 dB floor before accumulating MFCCs.
        peak = 0.0
        for mel in mel_blocks:
            peak = max(peak, float(np.max(mel)))
        floor = 10.0 * math.log10(max(peak, 1e-10)) - 80.0
    mfcc = _Moments(0, np.zeros(13), np.zeros(13))
    onset_blocks: list[NDArray[np.float64]] = []
    previous: NDArray[np.float64] | None = None
    while mel_blocks:
        # Release each retained block once its MFCCs and onsets are recorded.
        mel = mel_blocks.popleft()
        mel_db = power_to_db(mel)
        if floor is not None:
            mel_db = np.maximum(mel_db, floor)
        checkpoint()
        mfcc.add(librosa.feature.mfcc(S=mel_db, n_mfcc=13))
        flux_source = (
            mel_db if previous is None else np.concatenate((previous, mel_db), axis=1)
        )
        # Retain one column, not a view holding the preceding block alive.
        previous = mel_db[:, -1:].copy()
        onset: NDArray[np.float64] = np.maximum(np.diff(flux_source, axis=1), 0.0).mean(
            axis=0
        )
        onset_blocks.append(onset)
    onset = np.concatenate(onset_blocks)
    tempo = 0.0
    beat_strength = 0.0
    if samples.size >= 2 * sample_rate_hz and np.any(onset > 1e-6):
        tempo, beat_strength = _segment_rhythm(onset, sample_rate_hz, checkpoint)
    checkpoint()
    values = (
        tempo,
        float(centroid.mean[0]),
        float(centroid.variance()[0]),
        *(float(value) for value in mfcc.mean),
        *(float(value) for value in mfcc.variance()),
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Audio analysis produced nonfinite Genius features")
    rms = np.concatenate(rms_blocks)
    flatness = np.concatenate(flatness_blocks)
    # A relative floor avoids calling quiet recordings silence. Exclude silent
    # frames from flatness: their empty spectrum would otherwise look like noise.
    peak = float(np.max(rms))
    active = rms > peak * 0.001
    low, high = np.quantile(rms, (0.1, 0.9))
    dynamics = (
        min(60.0, 20 * math.log10(high / max(low, high * 0.001))) if high > 0 else 0.0
    )
    character = GeniusAudioCharacter(
        spectral_activity=float(np.mean(onset)) * sample_rate_hz / _HOP_SIZE,
        beat_strength=beat_strength,
        dynamic_range_db=dynamics,
        spectral_flatness=float(np.clip(np.mean(flatness[active]), 0, 1))
        if np.any(active)
        else 0.0,
        active_fraction=float(np.mean(active)),
    )
    return values, character


def profile_genius_pcm(
    pcm: bytes,
    *,
    sample_rate_hz: int = 22050,
    checkpoint: Callable[[], None] | None = None,
) -> GeniusAudioProfile:
    """Profile caller-decoded mono little-endian float32 PCM without I/O.

    Tracks longer than 40 seconds use 20-second ends and the remaining body.
    Shorter Tracks use the whole signal as their body, with unavailable ends.
    Silence has a finite zero profile; malformed or nonfinite input is rejected.
    """

    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        raise ValueError("Genius PCM requires a positive integer sample rate")
    if not pcm or len(pcm) % 4:
        raise ValueError("Genius PCM requires complete, nonempty float32 samples")
    samples: NDArray[np.float32] = np.frombuffer(pcm, dtype="<f4")
    if not np.all(np.isfinite(samples)):
        raise ValueError("Genius PCM contains nonfinite samples")
    duration = samples.size / sample_rate_hz
    end_size = _END_SECONDS * sample_rate_hz
    if samples.size <= 2 * end_size:
        body, character = _segment_features(samples, sample_rate_hz, check)
        return GeniusAudioProfile(duration, None, body, None, character)
    intro, _ = _segment_features(samples[:end_size], sample_rate_hz, check)
    body, character = _segment_features(
        samples[end_size:-end_size], sample_rate_hz, check
    )
    outro, _ = _segment_features(samples[-end_size:], sample_rate_hz, check)
    return GeniusAudioProfile(duration, intro, body, outro, character)


def _validated_features(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) != GENIUS_AUDIO_FEATURE_COUNT or not all(
        math.isfinite(value) for value in values
    ):
        raise ValueError("Genius audio segments require 29 finite features")
    return values


def _normalize(rows: list[tuple[float, ...]]) -> NDArray[np.float64]:
    values = np.asarray(rows, dtype=np.float64)
    # Scale before centering so even large finite externally supplied profiles
    # cannot overflow their mean or variance. Constant columns contribute zero.
    scale = np.max(np.abs(values), axis=0)
    scaled = values / np.where(scale > 0.0, scale, 1.0)
    centered = scaled - np.mean(scaled, axis=0)
    deviation = np.std(centered, axis=0)
    return centered / np.where(deviation > 1e-12, deviation, 1.0)


def _rank_vectors(rows: list[tuple[float, ...]]) -> NDArray[np.float64]:
    # Balance feature families instead of giving 26 cepstral statistics 26 votes.
    # MFCC0 mean includes recording gain; its variance describes dynamics, which
    # have dedicated measurements. Neither is used as timbre evidence here.
    weights = np.asarray(
        (
            0.1,
            0.15,
            0.1,
            0.0,
            *(0.4 / 12 for _ in range(12)),
            0.0,
            *(0.25 / 12 for _ in range(12)),
        ),
        dtype=np.float64,
    )
    return _normalize(rows) * np.sqrt(weights)


def _projection_orders(
    bodies: NDArray[np.float64], checkpoint: Callable[[], None]
) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    # Fixed trigonometric directions avoid random state/version-dependent draws.
    dimensions = np.arange(1, bodies.shape[1] + 1, dtype=np.float64)
    directions = np.stack(
        [
            np.cos(dimensions * (index + 1) * math.sqrt(2.0))
            for index in range(_PROJECTION_COUNT)
        ]
    )
    orders: list[NDArray[np.intp]] = []
    positions: list[NDArray[np.intp]] = []
    for direction in directions:
        checkpoint()
        order = np.argsort(bodies @ direction, kind="stable")
        inverse = np.empty(len(order), dtype=np.intp)
        inverse[order] = np.arange(len(order), dtype=np.intp)
        orders.append(order)
        positions.append(inverse)
    return np.stack(orders), np.stack(positions)


def _shortlist(
    seed: int,
    count: int,
    limit: int,
    orders: NDArray[np.intp] | None,
    positions: NDArray[np.intp] | None,
) -> NDArray[np.intp]:
    if orders is None or positions is None:
        return np.delete(np.arange(count, dtype=np.intp), seed)
    # The first window guarantees `limit` neighbors even when projections tie.
    # Smaller additional windows improve recall without multiplying work by N.
    windows: list[NDArray[np.intp]] = []
    for projection, (order, inverse) in enumerate(zip(orders, positions, strict=True)):
        width = max(16, (limit + 1) // 2 if projection == 0 else (limit + 7) // 8)
        position = int(inverse[seed])
        start = max(0, min(position - width, count - 2 * width - 1))
        windows.append(order[start : min(count, start + 2 * width + 1)])
    candidates = np.unique(np.concatenate(windows))
    return np.asarray(candidates[candidates != seed], dtype=np.intp)


def _distances(
    rows: NDArray[np.float64], origin: NDArray[np.float64]
) -> NDArray[np.float64]:
    differences = rows - origin
    distances: NDArray[np.float64] = np.sum(differences * differences, axis=1)
    # Equal distances can differ in the final floating-point subtraction bit.
    # Quantization preserves deterministic identity ordering for those ties.
    return np.round(distances, decimals=12)


def rank_genius_candidates(
    profiles: Mapping[int, GeniusAudioProfile],
    *,
    limit: int = 256,
    checkpoint: Callable[[], None] | None = None,
) -> dict[int, tuple[int, ...]]:
    """Return bounded native relationships, without an all-pairs distance matrix.

    Libraries up to 512 profiles use exact body neighbors. Larger Libraries use
    eight sorted projection neighborhoods, then exact distances within each
    bounded shortlist. Work is O(N log N + N*K*(D + log K)), memory O(N*D + N*K),
    with fixed feature dimension D<=33 and candidate cap K=256. Neighbor search is
    approximate above that small-Library threshold.

    Repeatedly choose the best seed-outro to candidate-intro transition among the
    three nearest remaining bodies. Without all three transition profiles, use
    their body order. Intro and outro share one normalization; body normalization
    is independent. Ties use Track IDs and input order never affects the result.
    """

    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if type(limit) is not int or not 0 <= limit <= _MAX_CANDIDATES:
        raise ValueError("Genius candidate limit must be between 0 and 256")
    identities = sorted(profiles)
    if not identities:
        return {}
    body_rows: list[tuple[float, ...]] = []
    end_rows: list[tuple[float, ...]] = []
    intros: dict[int, int] = {}
    outros: dict[int, int] = {}
    for index, identity in enumerate(identities):
        check()
        profile = profiles[identity]
        if not math.isfinite(profile.duration_seconds) or profile.duration_seconds <= 0:
            raise ValueError("Genius audio duration must be finite and positive")
        body_rows.append(_validated_features(profile.body))
        for segment, offsets in ((profile.intro, intros), (profile.outro, outros)):
            if segment is not None:
                offsets[index] = len(end_rows)
                end_rows.append(_validated_features(segment))
    if not limit or len(identities) == 1:
        return dict.fromkeys(identities, ())
    bodies = _rank_vectors(body_rows)
    characters = [profiles[identity].character for identity in identities]
    if all(character is not None for character in characters):
        character_rows: list[tuple[float, ...]] = [
            (
                character.spectral_activity,
                character.beat_strength,
                character.dynamic_range_db,
                character.spectral_flatness,
            )
            for character in characters
            if character is not None
        ]
        # The four new body measurements share 40% of distance. Optional vocal
        # inference cannot change the global graph: only some Tracks receive it.
        bodies = np.concatenate(
            (bodies * math.sqrt(0.6), _normalize(character_rows) * math.sqrt(0.1)),
            axis=1,
        )
    ends = _rank_vectors(end_rows) if end_rows else None
    orders, positions = (
        _projection_orders(bodies, check)
        if len(identities) > _EXACT_NEIGHBOR_LIMIT
        else (None, None)
    )
    size = min(limit, len(identities) - 1)
    result: dict[int, tuple[int, ...]] = {}
    for seed, identity in enumerate(identities):
        check()
        candidates = _shortlist(seed, len(identities), size, orders, positions)
        distances = _distances(bodies[candidates], bodies[seed])
        ordered = candidates[np.argsort(distances, kind="stable")]
        transitions: dict[int, float] = {}
        if ends is not None and seed in outros:
            available = [int(index) for index in candidates if int(index) in intros]
            if available:
                transition_values = _distances(
                    ends[[intros[index] for index in available]], ends[outros[seed]]
                )
                transitions = {
                    index: float(distance)
                    for index, distance in zip(
                        available, transition_values, strict=True
                    )
                }
        remaining = iter(int(index) for index in ordered)
        nearest = [next(remaining) for _ in range(min(3, len(ordered)))]
        chosen: list[int] = []
        while len(chosen) < size:
            check()
            winner = nearest[0]
            if transitions and all(index in transitions for index in nearest):
                winner = min(
                    nearest,
                    key=lambda index: transitions[index],
                )
            chosen.append(identities[winner])
            nearest.remove(winner)
            following = next(remaining, None)
            if following is not None:
                nearest.append(following)
        result[identity] = tuple(chosen)
    return result
