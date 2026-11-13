"""Musical correctness tests use known notes, never a mirrored DSP implementation."""

import numpy as np
import pytest
from numpy.typing import NDArray

from iOpenPod.app.tone_conversion import ToneArrangement, arrange_melody
from iOpenPod.app.tone_preview import tone_pcm
from iPodDB.alarms import AlarmToneNote

_RATE = 22050
_MELODY = (60, 62, 64, 67, 65, 64, 62, 60, 64, 67, 69, 67, 64, 60)


def _signal(*, fundamental: bool = True) -> NDArray[np.float32]:
    time = np.arange(_RATE // 2, dtype=np.float32) / _RATE
    return np.concatenate(
        [
            sum(
                np.sin(2 * np.pi * 440 * 2 ** ((note - 69) / 12) * h * time) / h
                for h in range(1 if fundamental else 2, 5)
            )
            * 0.2
            for note in _MELODY
        ]
    ).astype(np.float32)


def _accuracy(result: ToneArrangement) -> float:
    observed: list[int] = []
    for note in result.notes:
        pitch = round(69 + 12 * np.log2(note.frequency / 440)) if note.frequency else 0
        observed.extend([pitch] * note.duration_ms)
    expected = np.repeat(_MELODY, 500)
    count = min(len(observed), len(expected))
    return float(np.mean(np.abs(np.asarray(observed[:count]) - expected[:count]) <= 1))


@pytest.mark.parametrize(
    "accompaniment", [(), (65.406, 82.407, 98.0), (130.8128, 196.0, 261.6256)]
)
def test_melody_survives_louder_accompaniment(accompaniment: tuple[float, ...]) -> None:
    audio = _signal()
    if accompaniment:
        time = np.arange(len(audio), dtype=np.float32) / _RATE
        audio += sum(
            np.sin(2 * np.pi * frequency * time) * 0.4 for frequency in accompaniment
        )
    result = arrange_melody(
        audio, checkpoint=lambda: None, report=lambda _message: None
    )
    assert 6800 <= result.duration_ms <= 7200
    assert _accuracy(result) > 0.93
    assert all(note.duration_ms >= 70 for note in result.notes)


def test_missing_fundamental_preserves_octave() -> None:
    result = arrange_melody(
        _signal(fundamental=False),
        checkpoint=lambda: None,
        report=lambda _message: None,
    )
    assert _accuracy(result) > 0.85


@pytest.mark.parametrize(
    "audio",
    [
        np.zeros(_RATE * 7, dtype=np.float32),
        np.random.default_rng(42).normal(0, 0.15, _RATE * 7).astype(np.float32),
    ],
)
def test_silence_and_noise_do_not_become_invented_melodies(
    audio: NDArray[np.float32],
) -> None:
    with pytest.raises(ValueError, match=r"melody|melodic"):
        arrange_melody(audio, checkpoint=lambda: None, report=lambda _message: None)


def test_scans_beyond_a_silent_intro() -> None:
    phrase = _signal()
    audio = np.concatenate(
        (
            np.zeros(_RATE * 10, dtype=np.float32),
            phrase,
            np.zeros(_RATE, dtype=np.float32),
            phrase,
        )
    )
    result = arrange_melody(
        audio, checkpoint=lambda: None, report=lambda _message: None
    )
    assert result.source_start_seconds >= 9
    assert result.duration_ms > 5500


def test_cancellation_during_analysis_is_not_swallowed() -> None:
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise InterruptedError

    with pytest.raises(InterruptedError):
        arrange_melody(_signal(), checkpoint=checkpoint, report=lambda _message: None)


def test_preview_uses_saved_notes_and_real_silence() -> None:
    notes = (AlarmToneNote(440, 100), AlarmToneNote(0, 100), AlarmToneNote(660, 100))
    pcm = np.frombuffer(tone_pcm(notes), dtype="<i2")
    assert len(pcm) == 13230
    assert np.max(np.abs(pcm[:4410])) > 5000
    assert not np.any(pcm[4410:8820])
    with pytest.raises(ValueError, match="30 seconds"):
        tone_pcm((AlarmToneNote(440, 31000),))
