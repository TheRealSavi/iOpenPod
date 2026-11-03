"""Signal-level checks independent of the analysis implementation."""

from __future__ import annotations

from threading import Barrier, Event, Lock, get_ident
from typing import TYPE_CHECKING

import numpy as np
import pytest

from iOpenPod.app import phase_audio
from iOpenPod.app.phase_audio import PHASE_SAMPLE_RATE, analyze_phase_pcm
from iOpenPod.app.phase_hpss import separate_magnitude

if TYPE_CHECKING:
    from numpy.typing import NDArray


def test_spectral_blocks_overlap_and_checkpoints_stay_on_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm, _ = pulse_audio()
    expected = analyze_phase_pcm(pcm, length_ms=30_000, max_workers=1)
    original = separate_magnitude
    rendezvous = Barrier(2)
    owner = get_ident()
    workers: set[int] = set()

    def overlapping(
        magnitude: NDArray[np.float32],
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        workers.add(get_ident())
        rendezvous.wait(timeout=5)
        return original(magnitude)

    def checkpoint() -> None:
        assert get_ident() == owner

    monkeypatch.setattr(phase_audio, "separate_magnitude", overlapping)
    assert analyze_phase_pcm(pcm, length_ms=30_000, checkpoint=checkpoint) == expected
    assert len(workers) == 2


def test_cancellation_during_parallel_work_drains_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm, _ = pulse_audio()
    started, release = Event(), Event()
    lock = Lock()
    active: set[int] = set()
    owner = get_ident()
    calls: list[int] = []

    def blocked(*args: object, **kwargs: object) -> tuple[np.ndarray, np.ndarray]:
        del args, kwargs
        identity = get_ident()
        with lock:
            active.add(identity)
            calls.append(identity)
        started.set()
        try:
            assert release.wait(5)
            raise ValueError("worker interrupted")
        finally:
            with lock:
                active.remove(identity)

    def checkpoint() -> None:
        assert get_ident() == owner
        if started.is_set():
            release.set()
            raise RuntimeError("user cancellation")

    monkeypatch.setattr(phase_audio, "separate_magnitude", blocked)
    with pytest.raises(RuntimeError, match="user cancellation"):
        analyze_phase_pcm(pcm * 4, length_ms=120_000, checkpoint=checkpoint)
    assert not active
    assert 1 <= len(calls) <= 2


def test_parallel_worker_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    pcm, _ = pulse_audio()

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError("invalid spectral block")

    monkeypatch.setattr(phase_audio, "separate_magnitude", fail)
    with pytest.raises(ValueError, match="invalid spectral block"):
        analyze_phase_pcm(pcm, length_ms=30_000)


def pulse_audio() -> tuple[bytes, list[float]]:
    rate = PHASE_SAMPLE_RATE
    signal = np.zeros(30 * rate, dtype=np.float32)
    times = [float(t) for t in np.arange(2, 28, 0.5) if not 10 <= t < 13]
    width = round(0.05 * rate)
    for i, time in enumerate(times):
        frequency = (100, 800, 4000)[i % 3]
        burst = np.sin(2 * np.pi * frequency * np.arange(width) / rate) * np.hanning(
            width
        )
        start = round(time * rate)
        signal[start : start + width] += (0.8 * burst).astype(np.float32)
    return signal.astype("<f4").tobytes(), times


def test_onsets_follow_audio_attacks_beats_keep_pulse_and_silence_has_no_events() -> (
    None
):
    pcm, expected = pulse_audio()
    chart = analyze_phase_pcm(pcm, length_ms=30_000)
    actual = [event.time_q16 / 65536 for event in chart.transients]
    assert len(actual) >= len(expected) * 0.8
    assert (
        sum(min(abs(t - found) for found in actual) < 0.09 for t in expected)
        >= len(expected) * 0.8
    )
    assert len(chart.beats) >= 20
    times = [t.time_q16 for t in chart.transients] + [b.time_q16 for b in chart.beats]
    assert all(not 10.15 < time / 65536 < 12.9 for time in times)
    assert len({(t.low, t.mid, t.high) for t in chart.transients}) > 5
    assert all(0 <= v <= 31 for t in chart.transients for v in (t.low, t.mid, t.high))
    assert all(0 <= v <= 15 for b in chart.beats for v in (b.strength, b.accent))
    assert analyze_phase_pcm(pcm, length_ms=30_000, max_workers=1) == chart


@pytest.mark.parametrize("invalid_index", [100, 25 * PHASE_SAMPLE_RATE])
def test_silence_invalid_samples_duration_and_cancellation(invalid_index: int) -> None:
    pcm = np.zeros(30 * PHASE_SAMPLE_RATE, dtype="<f4").tobytes()
    chart = analyze_phase_pcm(pcm, length_ms=30_000)
    assert not chart.transients and not chart.beats
    with pytest.raises(ValueError, match="duration"):
        analyze_phase_pcm(pcm[:400], length_ms=30_000)
    corrupted = np.zeros(30 * PHASE_SAMPLE_RATE, dtype="<f4")
    corrupted[invalid_index] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        analyze_phase_pcm(corrupted.tobytes(), length_ms=30_000)

    def cancelled() -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        analyze_phase_pcm(pcm, length_ms=30_000, checkpoint=cancelled)


def test_local_pulse_tracks_a_tempo_change() -> None:
    rate = PHASE_SAMPLE_RATE
    signal = np.zeros(60 * rate, dtype=np.float32)
    width = round(0.05 * rate)
    burst = (
        np.sin(2 * np.pi * 150 * np.arange(width) / rate) * np.hanning(width)
    ).astype(np.float32)
    for time in (*np.arange(2, 26, 0.5), *np.arange(32, 58, 2 / 3)):
        first = round(float(time) * rate)
        signal[first : first + width] += burst
    chart = analyze_phase_pcm(signal.astype("<f4").tobytes(), length_ms=60_000)
    times = np.asarray([b.time_q16 / 65536 for b in chart.beats])
    for first, last, period in ((4, 20, 0.5), (40, 56, 2 / 3)):
        intervals = np.diff(times[(times > first) & (times < last)])
        assert len(intervals) >= 10
        assert abs(float(np.median(intervals)) - period) < 0.06


def test_pitched_phrase_keeps_continuing_drum_attacks_available() -> None:
    rate = PHASE_SAMPLE_RATE
    signal = np.zeros(30 * rate, dtype=np.float32)
    rng = np.random.default_rng(7)
    width = round(0.04 * rate)
    drum = (rng.normal(size=width) * np.hanning(width) * 0.3).astype(np.float32)
    drum_times = np.arange(1, 29, 0.5)
    for time in drum_times:
        first = round(float(time) * rate)
        signal[first : first + width] += drum
    melody_times = np.arange(8.23, 20, 0.8)
    width = round(0.65 * rate)
    ramp = round(0.03 * rate)
    shape = np.ones(width)
    shape[:ramp] = np.linspace(0, 1, ramp)
    shape[-ramp:] = np.linspace(1, 0, ramp)
    for index, time in enumerate(melody_times):
        frequency = (330, 440, 392, 494)[index % 4]
        note = np.sin(2 * np.pi * frequency * np.arange(width) / rate) * shape * 0.7
        first = round(float(time) * rate)
        signal[first : first + width] += note.astype(np.float32)
    pcm = signal.astype("<f4").tobytes()
    chart = analyze_phase_pcm(pcm, length_ms=30_000)
    times = np.asarray([event.time_q16 / 65536 for event in chart.transients])
    # Both lead and accompaniment are evidence. Native Phase owns the decision
    # about which of these real attacks fits its difficulty and spacing rules.
    melody = melody_times[(melody_times > 12) & (melody_times < 19)]
    assert sum(np.min(np.abs(times - t)) < 0.1 for t in melody) >= len(melody) * 0.8
    exposed = drum_times[(drum_times < 7) | (drum_times > 23)]
    assert sum(np.min(np.abs(times - t)) < 0.1 for t in exposed) >= len(exposed) * 0.8
    competing = [
        t for t in drum_times if 12 < t < 19 and np.min(np.abs(melody_times - t)) > 0.15
    ]
    assert (
        sum(np.min(np.abs(times - t)) < 0.1 for t in competing) >= len(competing) * 0.8
    )
    assert analyze_phase_pcm(pcm, length_ms=30_000, max_workers=1) == chart


def test_held_tone_with_vibrato_does_not_become_repeated_taps() -> None:
    time = np.arange(30 * PHASE_SAMPLE_RATE) / PHASE_SAMPLE_RATE
    shape = np.clip((time - 3) / 0.1, 0, 1) * np.clip((27 - time) / 0.1, 0, 1)
    phase = 2 * np.pi * 440 * time + 0.08 * np.sin(2 * np.pi * 5 * time)
    pcm = (0.5 * np.sin(phase) * shape).astype("<f4").tobytes()
    chart = analyze_phase_pcm(pcm, length_ms=30_000)
    assert any(2.9 < event.time_q16 / 65536 < 3.2 for event in chart.transients)
    assert not any(5 < event.time_q16 / 65536 < 25 for event in chart.transients)
