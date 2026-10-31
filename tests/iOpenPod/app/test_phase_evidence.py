"""Phase receives complete music evidence before it applies game difficulty."""

from itertools import pairwise

import numpy as np

from iOpenPod.app.phase_audio import PHASE_SAMPLE_RATE, analyze_phase_pcm
from iOpenPod.app.phase_hooks import direct_parts
from iOpenPod.app.phase_parts import PhasePart, PhasePartKind


def music_with_energy_change() -> bytes:
    rate = PHASE_SAMPLE_RATE
    t = np.arange(30 * rate) / rate
    signal = 0.09 * np.sin(2 * np.pi * 440 * t)
    rng = np.random.default_rng(3168)
    width = round(0.12 * rate)
    hit = rng.normal(size=width) * np.exp(-np.arange(width) / (rate * 0.025))
    for start in np.arange(1, 29, 0.5):
        first = round(float(start) * rate)
        signal[first : first + width] += hit * (0.12 if start < 15 else 0.8)
    return signal.astype("<f4").tobytes()


def test_incomplete_source_evidence_cannot_erase_full_mix_attacks() -> None:
    pcm = music_with_energy_change()
    count = 1 + len(pcm) // 4 // 256
    empty = PhasePart(
        PhasePartKind.VOCALS,
        np.zeros((3, count)),
        np.zeros(count),
        np.zeros((12, count)),
    )
    baseline = analyze_phase_pcm(pcm, length_ms=30000)
    assisted = analyze_phase_pcm(pcm, length_ms=30000, parts=(empty,))
    assert len(baseline.transients) > 35
    assert assisted == baseline


def test_beat_power_follows_percussive_energy_even_with_constant_harmony() -> None:
    chart = analyze_phase_pcm(music_with_energy_change(), length_ms=30000)
    quiet = [b.accent for b in chart.beats if 3 < b.time_q16 / 65536 < 12]
    loud = [b.accent for b in chart.beats if 18 < b.time_q16 / 65536 < 27]
    assert quiet and loud
    assert np.median(loud) >= np.median(quiet) + 3


def test_quiet_source_attack_uses_mix_scale_and_keeps_nearby_mix_timing() -> None:
    count = 400
    mix = np.zeros((3, count))
    mix[0, [40, 140, 240]] = 1
    source = np.zeros((3, count))
    source[0, [42, 90, 142, 190, 242, 290]] = 1
    part = PhasePart(
        PhasePartKind.GUITAR,
        source,
        np.full(count, 0.2),
        np.zeros((12, count)),
    )
    events = direct_parts(
        (part,),
        beats=[],
        length_ms=5000,
        checkpoint=lambda: None,
        mix_bands=mix,
        mix_energy=np.ones(count),
        mix_onsets=(40, 140, 240),
    )
    frames = [round(e.time_q16 * 22050 / (65536 * 256)) for e in events]
    assert frames == [40, 90, 140, 190, 240, 290]
    assert all(events[i].low == 31 for i in (0, 2, 4))
    assert all(0 < events[i].low < 20 for i in (1, 3, 5))


def test_lead_preference_can_affect_an_attack_already_present_in_the_mix() -> None:
    count = 400
    mix = np.zeros((3, count))
    mix[0, [40, 140, 240]] = [0.4, 1.0, 1.0]
    source = np.zeros((3, count))
    source[0, 42] = 0.4
    part = PhasePart(
        PhasePartKind.VOCALS,
        source,
        np.full(count, 0.3),
        np.zeros((12, count)),
    )

    def chart(parts: tuple[PhasePart, ...]) -> tuple[int, ...]:
        return tuple(
            event.low
            for event in direct_parts(
                parts,
                beats=[],
                length_ms=5000,
                checkpoint=lambda: None,
                mix_bands=mix,
                mix_energy=np.ones(count),
                mix_onsets=(40, 140, 240),
            )
        )

    baseline = chart(())
    assisted = chart((part,))
    assert assisted[0] > baseline[0]
    assert assisted[1:] == baseline[1:]


def test_codec_capacity_preserves_quieter_sections_of_a_long_track() -> None:
    count = 1 + 1800 * 22050 // 256
    frames = tuple(range(10, count, 6))
    mix = np.zeros((3, count))
    mix[0, list(frames)] = 1
    energy = np.ones(count)
    energy[: count // 2] = 0.2
    events = direct_parts(
        (),
        beats=[],
        length_ms=1800000,
        checkpoint=lambda: None,
        mix_bands=mix,
        mix_energy=energy,
        mix_onsets=frames,
    )
    expected = {round(frame * 256 * 65536 / 22050) for frame in frames}
    assert len(frames) > 20000
    assert 19000 < len(events) <= 20000
    assert all(event.time_q16 in expected for event in events)
    assert all(a.time_q16 < b.time_q16 for a, b in pairwise(events))
    quiet = [event for event in events if event.time_q16 < 900 * 65536]
    assert len(quiet) > 9000
