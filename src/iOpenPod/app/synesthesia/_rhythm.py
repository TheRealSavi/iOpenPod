"""Deterministic pulse, beat, downbeat, and tempo analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import librosa
import numpy as np

from ._signals import FloatArray, align, robust_unit
from .models import EventKind, MusicalEvent, TimeGrid

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class RhythmResult:
    onset: FloatArray
    pulse: FloatArray
    beat_phase: FloatArray
    tempo_bpm: FloatArray
    confidence: FloatArray
    events: tuple[MusicalEvent, ...]


def analyze_rhythm(
    onset: FloatArray,
    low_onset: FloatArray,
    *,
    sample_rate: int,
    hop_size: int,
    grid: TimeGrid,
    duration_seconds: float,
) -> RhythmResult:
    """Return measured rhythm; do not invent a metronome for weak evidence."""

    frame_count = grid.frame_count
    onset = np.clip(align(onset, frame_count), 0.0, 1.0).astype(np.float32)
    low_onset = np.clip(align(low_onset, frame_count), 0.0, 1.0).astype(np.float32)
    if frame_count < 8 or float(np.percentile(onset, 98)) < 0.08:
        return _unmetered(onset, frame_count)

    window = min(384, frame_count)
    pulse = align(
        librosa.beat.plp(
            onset_envelope=onset,
            sr=sample_rate,
            hop_length=hop_size,
            win_length=max(8, window),
            tempo_min=38,
            tempo_max=230,
        ),
        frame_count,
    )
    pulse = robust_unit(np.maximum(pulse, 0.0))
    _, detected = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sample_rate,
        hop_length=hop_size,
        sparse=True,
        units="frames",
    )
    beats: NDArray[np.int32] = np.asarray(detected, dtype=np.int32)
    beats = beats[(beats >= 0) & (beats < frame_count)]
    if len(beats) < 2:
        return _unmetered(onset, frame_count, pulse=pulse)

    intervals = np.diff(beats).astype(np.float32)
    median_interval = float(np.median(intervals))
    interval_cv = float(np.std(intervals) / max(median_interval, 1.0))
    regularity = math.exp(-4.0 * interval_cv)
    salience = float(np.mean(onset[beats]))
    expected_beats = max(2.0, duration_seconds / 0.75)
    coverage = min(1.0, len(beats) / expected_beats)
    confidence_value = float(
        np.clip(0.12 + 0.38 * regularity + 0.32 * salience + 0.18 * coverage, 0.0, 0.96)
    )
    if confidence_value < 0.28:
        return _unmetered(onset, frame_count, pulse=pulse)

    frames = np.arange(frame_count, dtype=np.int32)
    preceding = np.clip(
        np.searchsorted(beats, frames, side="right") - 1, 0, len(beats) - 1
    )
    following = np.clip(preceding + 1, 0, len(beats) - 1)
    before = beats[preceding]
    after = beats[following]
    span = np.where(after > before, after - before, median_interval)
    phase = np.clip((frames - before) / np.maximum(span, 1.0), 0.0, 1.0).astype(
        np.float32
    )
    interval_index = np.clip(preceding, 0, len(intervals) - 1)
    tempo = (
        60.0 * sample_rate / hop_size / np.maximum(intervals[interval_index], 1.0)
    ).astype(np.float32)
    supported = (frames >= beats[0] - median_interval * 0.5) & (
        frames <= beats[-1] + median_interval * 0.5
    )
    confidence = np.where(supported, confidence_value, 0.0).astype(np.float32)
    accents: FloatArray = (onset[beats] + np.float32(0.55) * low_onset[beats]).astype(
        np.float32, copy=False
    )
    downbeats, meter_confidence = _infer_downbeats(beats, accents)
    events = tuple(
        MusicalEvent(
            event_id=f"{'downbeat' if int(frame) in downbeats else 'beat'}-{index}",
            kind=EventKind.DOWNBEAT if int(frame) in downbeats else EventKind.BEAT,
            seconds=min(duration_seconds, grid.time_at(int(frame))),
            strength=float(np.clip(0.35 + 0.65 * onset[frame], 0.0, 1.0)),
            confidence=(
                confidence_value * meter_confidence
                if int(frame) in downbeats
                else confidence_value
            ),
        )
        for index, frame in enumerate(beats)
        if grid.time_at(int(frame)) <= duration_seconds
    )
    return RhythmResult(onset, pulse, phase, tempo, confidence, events)


def _infer_downbeats(
    beats: NDArray[np.int32], accents: FloatArray
) -> tuple[set[int], float]:
    candidates: list[tuple[float, int, int]] = []
    for meter in (3, 4):
        if len(beats) < meter * 2:
            continue
        scores = np.asarray(
            [float(np.mean(accents[offset::meter])) for offset in range(meter)],
            dtype=np.float32,
        )
        order = np.argsort(scores)
        best_offset = int(order[-1])
        contrast = float(scores[order[-1]] - scores[order[-2]])
        support = min(1.0, len(beats) / (meter * 3.0))
        candidates.append((contrast * support, meter, best_offset))
    if not candidates:
        return set(), 0.0
    score, meter, offset = max(candidates)
    confidence = float(np.clip(score / 0.22, 0.0, 0.90))
    if confidence < 0.30:
        return set(), 0.0
    return {int(value) for value in beats[offset::meter]}, confidence


def _unmetered(
    onset: FloatArray,
    frame_count: int,
    *,
    pulse: FloatArray | None = None,
) -> RhythmResult:
    zeros = np.zeros(frame_count, dtype=np.float32)
    return RhythmResult(
        onset,
        zeros if pulse is None else pulse,
        zeros.copy(),
        zeros.copy(),
        zeros.copy(),
        (),
    )


__all__ = ["RhythmResult", "analyze_rhythm"]
