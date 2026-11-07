"""Whole-mix measurement remains independent of optional Part fusion."""

from dataclasses import FrozenInstanceError
from threading import Event, Thread, get_ident
from typing import Any

import librosa
import numpy as np
import pytest
from numpy.typing import NDArray
from tests.iOpenPod.app.test_phase_audio import pulse_audio
from tests.iOpenPod.app.test_phase_hooks import part

from iOpenPod.app import phase_audio
from iOpenPod.app.phase_audio import (
    PHASE_SAMPLE_RATE,
    PhaseMixEvidence,
    analyze_phase_pcm,
    finish_phase_analysis,
    measure_phase_mix,
)
from iOpenPod.app.phase_hooks import direct_parts
from iOpenPod.app.phase_parts import PhasePartKind
from iPodDB.games import PhaseChart


@pytest.fixture(scope="module")
def measured_mix() -> PhaseMixEvidence:
    pcm, _ = pulse_audio()
    return measure_phase_mix(pcm, length_ms=30_000, max_workers=1)


@pytest.mark.parametrize("assisted", [False, True])
def test_split_measurement_and_fusion_match_the_original_entry_point(
    measured_mix: PhaseMixEvidence, assisted: bool
) -> None:
    pcm, _ = pulse_audio()
    source = part(
        PhasePartKind.GUITAR, [100, 200, 300], [0, 4, 7], count=measured_mix.frame_count
    )
    parts = (source,) if assisted else ()
    assert finish_phase_analysis(measured_mix, parts=parts) == analyze_phase_pcm(
        pcm, length_ms=30_000, parts=parts
    )


def test_fusion_reuses_immutable_mix_evidence_without_repeating_measurement(
    measured_mix: PhaseMixEvidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured = measured_mix.measurements
    assert measured is not None
    before = finish_phase_analysis(measured_mix)
    energy, magnitudes = measured.energy.copy(), measured.magnitudes.copy()

    def repeated_measurement(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Finishing measured evidence repeated spectral work")

    monkeypatch.setattr(phase_audio, "separate_magnitude", repeated_measurement)
    source = part(
        PhasePartKind.GUITAR, [100, 200, 300], [0, 4, 7], count=measured_mix.frame_count
    )
    assisted = finish_phase_analysis(measured_mix, parts=(source,))
    assert assisted.beats == before.beats
    assert finish_phase_analysis(measured_mix) == before
    assert np.array_equal(measured.energy, energy)
    assert np.array_equal(measured.magnitudes, magnitudes)
    assert measured.energy.flags.owndata and measured.magnitudes.flags.owndata
    with pytest.raises(FrozenInstanceError):
        setattr(measured_mix, "length_ms", 1)  # noqa: B010 - exercise the frozen guard
    with pytest.raises(ValueError, match="read-only"):
        measured.energy[0] = 0
    with pytest.raises(ValueError, match="read-only"):
        measured.magnitudes[0, 0] = 0


@pytest.mark.parametrize("quiet_kind", ["silence", "no_onsets"])
def test_silent_or_onset_free_mix_preserves_parts_only_analysis(
    monkeypatch: pytest.MonkeyPatch, quiet_kind: str
) -> None:
    if quiet_kind == "silence":
        pcm = bytes(30 * PHASE_SAMPLE_RATE * 4)
    else:
        pcm, _ = pulse_audio()

        def zero_strength(
            *,
            S: NDArray[np.floating[Any]],  # noqa: N803 - librosa API
            **_kwargs: object,
        ) -> NDArray[np.float64]:
            return np.zeros(S.shape[-1], dtype=np.float64)

        monkeypatch.setattr(librosa.onset, "onset_strength", zero_strength)
    evidence = measure_phase_mix(pcm, length_ms=30_000)
    assert evidence.measurements is None
    assert finish_phase_analysis(evidence) == PhaseChart()
    source = part(
        PhasePartKind.GUITAR, [100, 200, 300], [0, 4, 7], count=evidence.frame_count
    )
    expected = direct_parts(
        (source,), beats=[], length_ms=30_000, checkpoint=lambda: None
    )
    assert len(expected) == 3
    assert finish_phase_analysis(evidence, parts=(source,)) == PhaseChart(expected)


@pytest.mark.parametrize("silent", [False, True])
def test_fusion_rejects_misaligned_parts_even_when_mix_has_no_events(
    measured_mix: PhaseMixEvidence, silent: bool
) -> None:
    evidence = (
        measure_phase_mix(bytes(30 * PHASE_SAMPLE_RATE * 4), length_ms=30_000)
        if silent
        else measured_mix
    )
    source = part(
        PhasePartKind.GUITAR,
        [100, 200, 300],
        [0, 4, 7],
        count=evidence.frame_count + 1,
    )
    with pytest.raises(ValueError, match="decoded duration"):
        finish_phase_analysis(evidence, parts=(source,))


def test_measurement_cancellation_stays_on_its_coordinator_and_joins_dsp(
    measured_mix: PhaseMixEvidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The module fixture initializes the DSP libraries before the bounded waits.
    assert measured_mix.measurements is not None
    started, release, stop, dsp_exited = Event(), Event(), Event(), Event()
    caller_threads: set[int] = set()
    errors: list[BaseException] = []
    cancellation = InterruptedError("Stopped whole-mix measurement")

    def blocked(
        magnitude: NDArray[np.float32],
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        started.set()
        try:
            assert release.wait(3)
            return magnitude, magnitude
        finally:
            dsp_exited.set()

    def checkpoint() -> None:
        caller_threads.add(get_ident())
        if stop.is_set():
            raise cancellation

    def measure() -> None:
        try:
            pcm, _ = pulse_audio()
            measure_phase_mix(
                pcm, length_ms=30_000, max_workers=1, checkpoint=checkpoint
            )
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(phase_audio, "separate_magnitude", blocked)
    coordinator = Thread(target=measure)
    coordinator.start()
    try:
        assert started.wait(3)
        stop.set()
    finally:
        release.set()
        coordinator.join(5)
    assert not coordinator.is_alive() and dsp_exited.is_set()
    assert errors == [cancellation]
    assert caller_threads == {coordinator.ident}


def test_fusion_checks_cancellation_before_using_measured_evidence(
    measured_mix: PhaseMixEvidence,
) -> None:
    cancellation = InterruptedError("Stopped before fusion")

    def checkpoint() -> None:
        raise cancellation

    with pytest.raises(InterruptedError) as caught:
        finish_phase_analysis(measured_mix, checkpoint=checkpoint)
    assert caught.value is cancellation


@pytest.mark.parametrize("invalid", ["frames", "duration", "nonfinite", "workers"])
def test_measurement_retains_pcm_validation(invalid: str) -> None:
    samples = np.zeros(30 * PHASE_SAMPLE_RATE, dtype="<f4")
    if invalid == "nonfinite":
        samples[-1] = np.nan
    pcm = samples.tobytes() + (b"x" if invalid == "frames" else b"")
    with pytest.raises(ValueError):
        measure_phase_mix(
            pcm,
            length_ms=1000 if invalid == "duration" else 30_000,
            max_workers=3 if invalid == "workers" else 1,
        )
