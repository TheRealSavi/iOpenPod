from dataclasses import replace

import pytest

from iOpenPod.app.synesthesia import (
    FloatSeries,
    SectionProfile,
    SignalValidity,
    TrackAnalysis,
)
from iOpenPod.GUI.synesthesia.conductor import FieldConductor
from iOpenPod.GUI.synesthesia.persistent_world import TransportState


def test_low_confidence_beat_phase_preserves_its_circular_coordinate(
    synthetic_analysis: TrackAnalysis,
) -> None:
    phase = synthetic_analysis.timeline.rhythm.beat_phase
    phase = replace(
        phase,
        values=FloatSeries.from_values([0.92] * phase.grid.frame_count),
        confidence=FloatSeries.from_values([0.20] * phase.grid.frame_count),
        validity=SignalValidity.VALID,
    )
    rhythm = replace(synthetic_analysis.timeline.rhythm, beat_phase=phase)
    timeline = replace(synthetic_analysis.timeline, rhythm=rhythm)
    analysis = replace(synthetic_analysis, timeline=timeline)

    forcing = (
        FieldConductor(analysis)
        .advance(
            musical_time=3.0,
            delta_seconds=0.1,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing
    )

    assert forcing.beat_phase == pytest.approx(0.92)


def test_unavailable_energy_cannot_leak_through_section_energy(
    synthetic_analysis: TrackAnalysis,
) -> None:
    relative = replace(
        synthetic_analysis.timeline.energy.relative,
        validity=SignalValidity.UNAVAILABLE,
    )
    energy = replace(synthetic_analysis.timeline.energy, relative=relative)
    timeline = replace(synthetic_analysis.timeline, energy=energy)
    sections = tuple(
        replace(section, profile=SectionProfile(1.0, 1.0, 1.0, 1.0))
        for section in synthetic_analysis.sections
    )
    analysis = replace(synthetic_analysis, timeline=timeline, sections=sections)

    forcing = (
        FieldConductor(analysis)
        .advance(
            musical_time=3.0,
            delta_seconds=0.1,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing
    )

    assert forcing.section_energy == pytest.approx(0.0)
