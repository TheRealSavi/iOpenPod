from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from iOpenPod.app.synesthesia import (
    AnalysisIssueSeverity,
    AnalysisRequest,
    DecodedAudio,
    DeterministicMusicAnalyzer,
    EventKind,
    SignalValidity,
    SourceKind,
)

if TYPE_CHECKING:
    from iOpenPod.app.synesthesia import TrackAnalysis


def test_analysis_distinguishes_sections_energy_spectrum_and_events(
    synthetic_analysis: TrackAnalysis,
) -> None:
    analysis = synthetic_analysis

    assert len(analysis.sections) == 3
    assert analysis.sections[0].label == "A"
    assert analysis.sections[1].label == "B"
    assert analysis.sections[2].label == "C"
    assert analysis.sections[0].end_seconds == pytest.approx(6.0, abs=0.7)
    assert analysis.sections[1].end_seconds == pytest.approx(12.0, abs=0.7)

    intro = analysis.sample(3.0)
    middle = analysis.sample(9.0)
    finale = analysis.sample(15.0)
    assert intro.section.section_id != middle.section.section_id
    assert middle.section.section_id != finale.section.section_id
    assert middle.energy.loudness_dbfs.value > intro.energy.loudness_dbfs.value + 8.0
    assert intro.spectrum.band_distribution.component("bass") > 0.85
    assert finale.spectrum.band_distribution.component("presence") > 0.25
    assert middle.layers.percussive.value > intro.layers.percussive.value + 0.1

    kinds = {event.kind for event in analysis.events}
    assert EventKind.ONSET in kinds
    assert EventKind.BEAT in kinds
    assert EventKind.DOWNBEAT in kinds
    assert EventKind.SECTION_BOUNDARY in kinds
    assert len(analysis.timeline.spectrum.band_levels_dbfs.components) == 7
    assert {source.kind for source in analysis.sources} == {
        SourceKind.HARMONIC,
        SourceKind.PERCUSSIVE,
    }


def test_silence_does_not_invent_tempo_pitch_events_or_sections() -> None:
    sample_rate = 16_000
    samples = np.ascontiguousarray(np.zeros((sample_rate * 4, 2), dtype=np.float32))

    analysis = DeterministicMusicAnalyzer().analyze(
        DecodedAudio(sample_rate, samples),
        AnalysisRequest(title="Silence"),
        title="Silence",
        checkpoint=lambda: None,
        progress=lambda _progress: None,
    )

    frame = analysis.sample(2.0)
    assert len(analysis.sections) == 1
    assert not analysis.events
    assert frame.rhythm.tempo_bpm.confidence == 0.0
    assert frame.harmony.pitch_midi.confidence == 0.0
    assert analysis.timeline.spatial.width.validity is SignalValidity.LIMITED
    assert any(
        issue.severity is AnalysisIssueSeverity.DEGRADED for issue in analysis.issues
    )


def test_stationary_tone_does_not_invent_structure_or_meter() -> None:
    sample_rate = 16_000
    times = np.arange(sample_rate * 8, dtype=np.float32) / sample_rate
    mono = (0.2 * np.sin(2.0 * np.pi * 220.0 * times)).astype(np.float32)
    samples = np.ascontiguousarray(np.column_stack((mono, -mono)))

    analysis = DeterministicMusicAnalyzer().analyze(
        DecodedAudio(sample_rate, samples),
        AnalysisRequest(title="Stationary tone"),
        title="Stationary tone",
        checkpoint=lambda: None,
        progress=lambda _progress: None,
    )

    assert len(analysis.sections) == 1
    frame = analysis.sample(4.0)
    assert frame.energy.loudness_dbfs.value == pytest.approx(-17.0, abs=1.0)
    assert frame.spectrum.band_distribution.component("bass") > 0.95
    assert frame.rhythm.tempo_bpm.confidence == 0.0
    assert not analysis.events


def test_result_is_immutable_and_preserves_signal_units(
    synthetic_analysis: TrackAnalysis,
) -> None:
    signal = synthetic_analysis.timeline.energy.loudness_dbfs

    assert isinstance(signal.values.data, bytes)
    assert signal.unit == "dBFS"
    assert signal.values.count == synthetic_analysis.timeline.grid.frame_count
    assert 0.0 <= signal.sample(9.0).confidence <= 1.0


def test_music_frame_preserves_each_sampled_signal_contract(
    synthetic_analysis: TrackAnalysis,
) -> None:
    seconds = 9.0
    frame = synthetic_analysis.sample(seconds)
    timeline = synthetic_analysis.timeline

    assert frame.energy.loudness_dbfs == timeline.energy.loudness_dbfs.sample(seconds)
    assert frame.energy.relative == timeline.energy.relative.sample(seconds)
    assert frame.energy.crest_db == timeline.energy.crest_db.sample(seconds)
    assert frame.rhythm.onset_strength == timeline.rhythm.onset_strength.sample(seconds)
    assert frame.rhythm.pulse == timeline.rhythm.pulse.sample(seconds)
    assert frame.rhythm.beat_phase == timeline.rhythm.beat_phase.sample(seconds)
    assert frame.rhythm.tempo_bpm == timeline.rhythm.tempo_bpm.sample(seconds)
    assert frame.spectrum.band_levels_dbfs == timeline.spectrum.band_levels_dbfs.sample(
        seconds
    )
    assert (
        frame.spectrum.band_distribution
        == timeline.spectrum.band_distribution.sample(seconds)
    )
    assert frame.spectrum.positive_flux == timeline.spectrum.positive_flux.sample(
        seconds
    )
    assert frame.spectrum.centroid_hz == timeline.spectrum.centroid_hz.sample(seconds)
    assert frame.spectrum.bandwidth_hz == timeline.spectrum.bandwidth_hz.sample(seconds)
    assert frame.spectrum.rolloff_hz == timeline.spectrum.rolloff_hz.sample(seconds)
    assert frame.timbre.flatness == timeline.timbre.flatness.sample(seconds)
    assert frame.timbre.contrast == timeline.timbre.contrast.sample(seconds)
    assert frame.timbre.change == timeline.timbre.change.sample(seconds)
    assert frame.harmony.chroma == timeline.harmony.chroma.sample(seconds)
    assert frame.harmony.coherence == timeline.harmony.coherence.sample(seconds)
    assert frame.harmony.change == timeline.harmony.change.sample(seconds)
    assert frame.harmony.pitch_midi == timeline.harmony.pitch_midi.sample(seconds)
    assert frame.spatial.pan == timeline.spatial.pan.sample(seconds)
    assert frame.spatial.width == timeline.spatial.width.sample(seconds)
    assert frame.spatial.correlation == timeline.spatial.correlation.sample(seconds)
    assert frame.layers.bass_register == timeline.layers.bass_register.sample(seconds)
    assert frame.layers.harmonic == timeline.layers.harmonic.sample(seconds)
    assert frame.layers.percussive == timeline.layers.percussive.sample(seconds)
    assert frame.layers.noise == timeline.layers.noise.sample(seconds)
    assert frame.section_novelty == timeline.structure.novelty.sample(seconds)
    assert frame.section_progress == timeline.structure.section_progress.sample(seconds)

    assert frame.harmony.coherence.confidence == frame.harmony.chroma.confidence
    assert frame.harmony.pitch_midi.confidence != frame.harmony.coherence.confidence
