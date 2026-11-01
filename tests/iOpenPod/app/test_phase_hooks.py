"""Authored part evidence tests musical identity and recurring phrases."""

from collections.abc import Sequence

import numpy as np
import pytest

from iOpenPod.app.phase_audio import analyze_phase_pcm
from iOpenPod.app.phase_hooks import PhasePassage, direct_parts, recognize_hooks
from iOpenPod.app.phase_parts import PhasePart, PhasePartKind


def part(
    kind: PhasePartKind,
    frames: Sequence[int],
    pitches: Sequence[int],
    *,
    count: int = 1400,
    level: float = 0.5,
) -> PhasePart:
    bands = np.zeros((3, count))
    chroma = np.zeros((12, count))
    for index, frame in enumerate(frames):
        bands[index % 3, frame] = 1
        end = frames[index + 1] if index + 1 < len(frames) else count
        chroma[pitches[index % len(pitches)], frame:end] = 1
    return PhasePart(kind, bands, np.full(count, level), chroma, bands * level)


def test_recurring_hook_matches_pitch_and_rhythm_with_expressive_timing() -> None:
    first = np.array([40, 90, 160, 220, 310, 370], dtype=np.int64)
    shifted = (first.astype(np.float64) - first[0]) * 1.1 + 800
    second = shifted.round().astype(np.int64)
    frames = np.concatenate((first, second))
    source = part(PhasePartKind.GUITAR, frames.tolist(), [0, 4, 7, 5, 4, 0])
    hooks = recognize_hooks(source, frames, checkpoint=lambda: None)
    assert len(hooks) == 1
    assert hooks[0].kind == PhasePartKind.GUITAR
    assert hooks[0].occurrences == (tuple(first), tuple(second))


def test_same_pitch_collection_in_a_different_order_is_not_the_same_hook() -> None:
    frames = np.array(
        [40, 90, 160, 220, 310, 370, 840, 890, 960, 1020, 1110, 1170], dtype=np.int64
    )
    source = part(
        PhasePartKind.VOCALS, frames.tolist(), [0, 4, 7, 5, 4, 0, 7, 0, 4, 0, 5, 4]
    )
    assert not recognize_hooks(source, frames, checkpoint=lambda: None)


def test_a_steady_single_pitch_pulse_is_not_a_hook() -> None:
    frames = np.arange(40, 1300, 50, dtype=np.int64)
    source = part(PhasePartKind.BASS, frames.tolist(), [0])
    assert not recognize_hooks(source, frames, checkpoint=lambda: None)


def test_returning_guitar_hook_preserves_drums_as_the_passage_anchor() -> None:
    guitar = part(
        PhasePartKind.GUITAR,
        [40, 90, 160, 220, 310, 370, 840, 890, 960, 1020, 1110, 1170],
        [0, 4, 7, 5, 4, 0],
        level=0.45,
    )
    drums = part(PhasePartKind.DRUMS, list(range(25, 1400, 50)), [0], level=0.65)
    passages: list[PhasePassage] = []
    events = direct_parts(
        (drums, guitar),
        beats=[],
        length_ms=16000,
        checkpoint=lambda: None,
        report=passages.append,
    )
    assert all(p.kind == PhasePartKind.DRUMS for p in passages)
    times = [e.time_q16 * 22050 / (65536 * 256) for e in events]
    assert all(
        min(abs(t - frame) for t in times) < 1
        for frame in (40, 90, 160, 220, 310, 840, 890, 960)
    )


def test_vocal_exit_hands_focus_to_guitar_without_moving_attacks() -> None:
    count = 1035
    vocals = part(
        PhasePartKind.VOCALS, [40, 95, 170, 240], [0, 4, 7, 0], count=count, level=0.8
    )
    vocal_energy = vocals.energy.copy()
    vocal_energy[344:] = 0
    vocals = PhasePart(
        vocals.kind, vocals.bands, vocal_energy, vocals.chroma, vocals.magnitudes
    )
    guitar = part(
        PhasePartKind.GUITAR,
        [380, 440, 510, 580, 740, 810, 880, 950],
        [7, 5, 4, 0],
        count=count,
        level=0.7,
    )
    passages: list[PhasePassage] = []
    events = direct_parts(
        (vocals, guitar),
        beats=[],
        length_ms=12000,
        checkpoint=lambda: None,
        report=passages.append,
    )
    assert passages[0].kind == PhasePartKind.VOCALS
    assert all(p.kind == PhasePartKind.GUITAR for p in passages[1:])
    expected = [40, 95, 170, 240, 380, 440, 510, 580, 740, 810, 880, 950]
    assert [e.time_q16 for e in events] == [
        round(f * 256 * 65536 / 22050) for f in expected
    ]


@pytest.mark.parametrize("drum_level", [0.01, 0.65])
def test_drum_break_and_inaudible_drums_leave_melody_available(
    drum_level: float,
) -> None:
    count = 1035
    drums = part(
        PhasePartKind.DRUMS,
        [40, 100, 160, 220, 280],
        [0],
        count=count,
        level=drum_level,
    )
    guitar_frames = list(range(60, 1000, 60))
    guitar = part(
        PhasePartKind.GUITAR,
        guitar_frames,
        [0, 4, 7, 5],
        count=count,
        level=0.7,
    )
    passages: list[PhasePassage] = []
    events = direct_parts(
        (drums, guitar),
        beats=[],
        length_ms=12000,
        checkpoint=lambda: None,
        report=passages.append,
    )
    assert passages[0].kind == (
        PhasePartKind.DRUMS if drum_level == 0.65 else PhasePartKind.GUITAR
    )
    assert all(p.kind == PhasePartKind.GUITAR for p in passages[1:])
    times = {event.time_q16 for event in events}
    assert all(round(f * 256 * 65536 / 22050) in times for f in guitar_frames)


def test_inaudible_leakage_and_empty_stems_cannot_generate_notes() -> None:
    vocals = part(
        PhasePartKind.VOCALS, list(range(40, 1400, 50)), [0, 4, 7], level=1e-7
    )
    guitar = part(PhasePartKind.GUITAR, [100, 200, 300], [0, 4, 7], level=0.8)
    passages: list[PhasePassage] = []
    events = direct_parts(
        (vocals, guitar),
        beats=[],
        length_ms=16000,
        checkpoint=lambda: None,
        report=passages.append,
    )
    assert events
    assert all(p.kind == PhasePartKind.GUITAR for p in passages)
    empty = PhasePart(
        PhasePartKind.VOCALS,
        np.zeros((3, 100)),
        np.zeros(100),
        np.zeros((12, 100)),
        np.zeros((3, 100)),
    )
    assert not direct_parts(
        (empty,), beats=[], length_ms=16000, checkpoint=lambda: None
    )


@pytest.mark.parametrize("support_kind", [PhasePartKind.DRUMS, PhasePartKind.GUITAR])
def test_sustained_lead_preserves_audible_supporting_attacks(
    support_kind: PhasePartKind,
) -> None:
    # The game chooses difficulty after reading this evidence. Holding a vocal
    # note must not erase the quarter-second attacks underneath it.
    frames = [round(t * 22050 / 256) for t in np.arange(0.125, 16, 0.25)]
    lead_frames = frames[1::8]
    vocals = part(PhasePartKind.VOCALS, lead_frames, [0], level=1.0)
    support = part(support_kind, frames, [0], level=0.65)
    passages: list[PhasePassage] = []
    events = direct_parts(
        (support, vocals),
        beats=[],
        length_ms=16000,
        checkpoint=lambda: None,
        report=passages.append,
    )
    expected_kind = (
        PhasePartKind.DRUMS
        if support_kind == PhasePartKind.DRUMS
        else PhasePartKind.VOCALS
    )
    assert all(p.kind == expected_kind for p in passages)
    assert [e.time_q16 for e in events] == [
        round(frame * 256 * 65536 / 22050) for frame in frames
    ]
    lead_times = {round(frame * 256 * 65536 / 22050) for frame in lead_frames}
    lead_strengths = [
        e.low + e.mid + e.high for e in events if e.time_q16 in lead_times
    ]
    support_strengths = [
        e.low + e.mid + e.high for e in events if e.time_q16 not in lead_times
    ]
    if support_kind != PhasePartKind.DRUMS:
        assert min(lead_strengths) > max(support_strengths)


def test_malformed_part_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid Phase source"):
        PhasePart(
            PhasePartKind.VOCALS,
            np.zeros((3, 10)),
            np.full(10, np.nan),
            np.zeros((12, 10)),
            np.zeros((3, 10)),
        )


@pytest.mark.parametrize("misaligned", [False, True])
def test_stereo_source_evidence_survives_a_silent_mono_fold(misaligned: bool) -> None:
    # Opposite-polarity stereo can cancel in the mono pulse signal, while its
    # separately measured source still has audible attacks.
    samples = np.zeros(30 * 22050, dtype="<f4")
    count = 1 + len(samples) // 256 + int(misaligned)
    source = part(PhasePartKind.GUITAR, [100, 200, 300], [0, 4, 7], count=count)
    if misaligned:
        with pytest.raises(ValueError, match="decoded duration"):
            analyze_phase_pcm(samples.tobytes(), length_ms=30000, parts=(source,))
    else:
        chart = analyze_phase_pcm(samples.tobytes(), length_ms=30000, parts=(source,))
        assert len(chart.transients) == 3
        assert not chart.beats
