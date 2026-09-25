from dataclasses import replace

import numpy as np
import pytest

from iOpenPod.app.synesthesia import (
    AnalysisRequest,
    DecodedAudio,
    DeterministicMusicAnalyzer,
    EventKind,
    MusicalEvent,
    SignalValidity,
    TrackAnalysis,
)
from iOpenPod.GUI.synesthesia.conductor import FieldConductor
from iOpenPod.GUI.synesthesia.persistent_world import TransportState


def test_conductor_preserves_independent_section_and_spectral_controls(
    synthetic_analysis: TrackAnalysis,
) -> None:
    conductor = FieldConductor(synthetic_analysis)

    intro = conductor.advance(
        musical_time=3.0,
        delta_seconds=1.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    ).forcing
    middle = conductor.advance(
        musical_time=9.0,
        delta_seconds=1.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    ).forcing
    finale = conductor.advance(
        musical_time=15.0,
        delta_seconds=1.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    ).forcing

    assert intro.section_identity < middle.section_identity < finale.section_identity
    assert middle.activity > intro.activity
    assert finale.brightness > intro.brightness
    assert len({intro.palette_hue, middle.palette_hue, finale.palette_hue}) == 3
    assert middle.percussive_layer > intro.percussive_layer


def test_conductor_emits_section_boundaries_once_per_transport_epoch(
    synthetic_analysis: TrackAnalysis,
) -> None:
    conductor = FieldConductor(synthetic_analysis)
    conductor.advance(
        musical_time=5.5,
        delta_seconds=0.1,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=6.6,
        delta_seconds=0.1,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )
    repeated = conductor.advance(
        musical_time=6.6,
        delta_seconds=0.1,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    assert any(
        event.kind is EventKind.SECTION_BOUNDARY for event in crossing.crossed_events
    )
    assert not any(
        event.kind is EventKind.SECTION_BOUNDARY for event in repeated.crossed_events
    )


def test_event_kinds_reach_distinct_presentation_systems(
    synthetic_analysis: TrackAnalysis,
) -> None:
    source_id = synthetic_analysis.sources[0].source_id
    events = tuple(
        MusicalEvent(
            event_id=f"event-{kind.value}",
            kind=kind,
            seconds=float(index),
            strength=1.0,
            confidence=1.0,
            source_id=source_id if kind is EventKind.SOURCE_ENTRANCE else None,
        )
        for index, kind in enumerate(
            (
                EventKind.ONSET,
                EventKind.DOWNBEAT,
                EventKind.SECTION_BOUNDARY,
                EventKind.SOURCE_ENTRANCE,
            ),
            start=1,
        )
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.0,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=5.0,
        delta_seconds=0.1,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    assert {
        getattr(impulse, "character", None) for impulse in crossing.forcing.impulses
    } == {"burst", "laser", "rift", "source-flare"}


def test_dense_onsets_are_edited_into_bounded_salient_bursts(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = tuple(
        MusicalEvent(
            event_id=f"dense-onset-{index}",
            kind=EventKind.ONSET,
            seconds=1.0 + index * 0.03,
            strength=0.82 + index * 0.01,
            confidence=0.92,
        )
        for index in range(10)
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=1.4,
        delta_seconds=0.5,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    bursts = [
        impulse
        for impulse in crossing.forcing.impulses
        if impulse.character.value == "burst"
    ]
    assert 1 <= len(bursts) <= 2


def test_dense_onset_edit_is_invariant_to_render_cadence(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = tuple(
        MusicalEvent(
            event_id=f"dense-onset-{index}",
            kind=EventKind.ONSET,
            seconds=1.0 + index * 0.03,
            strength=0.82 + index * 0.01,
            confidence=0.92,
        )
        for index in range(10)
    )
    analysis = replace(synthetic_analysis, events=events)

    coarse = FieldConductor(analysis)
    coarse.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )
    coarse_ids = [
        impulse.musical_event_id
        for impulse in coarse.advance(
            musical_time=1.4,
            delta_seconds=0.5,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        ).forcing.impulses
    ]

    fine = FieldConductor(analysis)
    fine.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )
    fine_ids: list[str] = []
    previous = 0.9
    for frame in range(1, 31):
        musical_time = 0.9 + frame / 60.0
        fine_ids.extend(
            impulse.musical_event_id
            for impulse in fine.advance(
                musical_time=musical_time,
                delta_seconds=musical_time - previous,
                transport_state=TransportState.PLAYING,
                transport_epoch=0,
            ).forcing.impulses
        )
        previous = musical_time

    assert coarse_ids == ["dense-onset-9"]
    assert fine_ids == coarse_ids


def test_sustained_onsets_remain_punctuation_instead_of_a_continuous_overlay(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = tuple(
        MusicalEvent(
            event_id=f"sustained-onset-{index}",
            kind=EventKind.ONSET,
            seconds=1.0 + index * 0.2,
            strength=0.90,
            confidence=0.95,
        )
        for index in range(20)
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=5.0,
        delta_seconds=4.1,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )
    bursts = [
        impulse
        for impulse in crossing.forcing.impulses
        if impulse.character.value == "burst"
    ]

    assert len(bursts) <= 7


def test_onset_punctuation_keeps_the_strongest_event_in_each_window(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = (
        MusicalEvent("early-onset", EventKind.ONSET, 1.0, 0.60, 0.95),
        MusicalEvent("strongest-onset", EventKind.ONSET, 2.0, 0.98, 0.95),
        MusicalEvent("later-onset", EventKind.ONSET, 6.0, 0.90, 0.95),
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=6.1,
        delta_seconds=5.2,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    assert [impulse.musical_event_id for impulse in crossing.forcing.impulses] == [
        "strongest-onset",
        "later-onset",
    ]


def test_only_salient_spaced_beats_are_promoted_to_laser_accents(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = (
        MusicalEvent("weak-beat", EventKind.BEAT, 1.0, 0.48, 0.90),
        MusicalEvent("accent-beat-a", EventKind.BEAT, 1.2, 0.96, 0.92),
        MusicalEvent("accent-beat-too-soon", EventKind.BEAT, 1.4, 0.98, 0.94),
        MusicalEvent("accent-beat-still-too-soon", EventKind.BEAT, 2.0, 0.94, 0.90),
        MusicalEvent("accent-beat-b", EventKind.BEAT, 6.6, 0.94, 0.90),
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    crossing = conductor.advance(
        musical_time=6.7,
        delta_seconds=5.8,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    lasers = [
        impulse
        for impulse in crossing.forcing.impulses
        if impulse.character.value == "laser"
    ]
    assert [impulse.musical_event_id for impulse in lasers] == [
        "accent-beat-too-soon",
        "accent-beat-b",
    ]


def test_beat_near_a_downbeat_is_suppressed_across_render_frames(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = (
        MusicalEvent("nearby-beat", EventKind.BEAT, 1.0, 0.98, 0.94),
        MusicalEvent("following-downbeat", EventKind.DOWNBEAT, 1.4, 0.90, 0.80),
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))
    conductor.advance(
        musical_time=0.9,
        delta_seconds=0.0,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    before_downbeat = conductor.advance(
        musical_time=1.1,
        delta_seconds=0.2,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )
    crossing_downbeat = conductor.advance(
        musical_time=1.5,
        delta_seconds=0.4,
        transport_state=TransportState.PLAYING,
        transport_epoch=0,
    )

    assert not any(
        impulse.character.value == "laser"
        for impulse in before_downbeat.forcing.impulses
    )
    assert [
        impulse.musical_event_id
        for impulse in crossing_downbeat.forcing.impulses
        if impulse.character.value == "laser"
    ] == ["following-downbeat"]


def test_impact_edit_plan_repeats_deterministically_after_a_transport_epoch(
    synthetic_analysis: TrackAnalysis,
) -> None:
    events = (
        MusicalEvent("onset-a", EventKind.ONSET, 1.0, 0.72, 0.90),
        MusicalEvent("onset-b", EventKind.ONSET, 2.0, 0.98, 0.95),
        MusicalEvent("beat-a", EventKind.BEAT, 6.5, 0.96, 0.92),
    )
    conductor = FieldConductor(replace(synthetic_analysis, events=events))

    def play_interval(epoch: int) -> tuple[tuple[object, ...], ...]:
        conductor.advance(
            musical_time=0.9,
            delta_seconds=0.0,
            transport_state=TransportState.PLAYING,
            transport_epoch=epoch,
        )
        crossing = conductor.advance(
            musical_time=6.6,
            delta_seconds=5.7,
            transport_state=TransportState.PLAYING,
            transport_epoch=epoch,
        )
        return tuple(
            (
                impulse.musical_event_id,
                impulse.origin,
                impulse.amplitude,
                impulse.character,
                impulse.speed,
                impulse.decay_seconds,
            )
            for impulse in crossing.forcing.impulses
        )

    first = play_interval(0)
    replayed = play_interval(1)

    assert first == replayed
    assert [signature[0] for signature in first] == ["onset-b", "beat-a"]


def test_silence_does_not_invent_frequency_or_timbre_forcing() -> None:
    sample_rate = 16_000
    analysis = DeterministicMusicAnalyzer().analyze(
        DecodedAudio(
            sample_rate,
            np.ascontiguousarray(np.zeros((sample_rate * 4, 2), dtype=np.float32)),
        ),
        AnalysisRequest(title="Silence"),
        title="Silence",
        checkpoint=lambda: None,
        progress=lambda _progress: None,
    )
    forcing = (
        FieldConductor(analysis)
        .advance(
            musical_time=2.0,
            delta_seconds=5.0,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing
    )

    assert forcing.low_frequency_mass < 0.01
    assert forcing.fine_excitation < 0.01
    assert forcing.brightness < 0.01
    assert forcing.timbral_noise < 0.01


def test_conductor_neutralizes_unavailable_and_limits_degraded_evidence(
    synthetic_analysis: TrackAnalysis,
) -> None:
    timeline = synthetic_analysis.timeline
    unavailable = SignalValidity.UNAVAILABLE
    unavailable_analysis = replace(
        synthetic_analysis,
        timeline=replace(
            timeline,
            energy=replace(
                timeline.energy,
                loudness_dbfs=replace(
                    timeline.energy.loudness_dbfs, validity=unavailable
                ),
                relative=replace(timeline.energy.relative, validity=unavailable),
            ),
            rhythm=replace(
                timeline.rhythm,
                onset_strength=replace(
                    timeline.rhythm.onset_strength, validity=unavailable
                ),
                pulse=replace(timeline.rhythm.pulse, validity=unavailable),
                beat_phase=replace(timeline.rhythm.beat_phase, validity=unavailable),
            ),
            spectrum=replace(
                timeline.spectrum,
                band_levels_dbfs=replace(
                    timeline.spectrum.band_levels_dbfs, validity=unavailable
                ),
                band_distribution=replace(
                    timeline.spectrum.band_distribution, validity=unavailable
                ),
                positive_flux=replace(
                    timeline.spectrum.positive_flux, validity=unavailable
                ),
                centroid_hz=replace(
                    timeline.spectrum.centroid_hz, validity=unavailable
                ),
            ),
            timbre=replace(
                timeline.timbre,
                flatness=replace(timeline.timbre.flatness, validity=unavailable),
                change=replace(timeline.timbre.change, validity=unavailable),
            ),
            harmony=replace(
                timeline.harmony,
                chroma=replace(timeline.harmony.chroma, validity=unavailable),
                coherence=replace(timeline.harmony.coherence, validity=unavailable),
            ),
            spatial=replace(
                timeline.spatial,
                pan=replace(timeline.spatial.pan, validity=unavailable),
                width=replace(timeline.spatial.width, validity=unavailable),
            ),
            layers=replace(
                timeline.layers,
                bass_register=replace(
                    timeline.layers.bass_register, validity=unavailable
                ),
                harmonic=replace(timeline.layers.harmonic, validity=unavailable),
                percussive=replace(timeline.layers.percussive, validity=unavailable),
                noise=replace(timeline.layers.noise, validity=unavailable),
            ),
            structure=replace(
                timeline.structure,
                novelty=replace(timeline.structure.novelty, validity=unavailable),
                section_progress=replace(
                    timeline.structure.section_progress, validity=unavailable
                ),
            ),
        ),
    )
    forcing = (
        FieldConductor(unavailable_analysis)
        .advance(
            musical_time=9.0,
            delta_seconds=5.0,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing
    )

    assert forcing.activity < 0.01
    assert forcing.low_frequency_mass < 0.01
    assert forcing.fine_excitation < 0.01
    assert forcing.harmonic_coherence == pytest.approx(0.5)
    assert forcing.brightness < 0.01
    assert forcing.timbral_noise < 0.01
    assert forcing.stereo_width < 0.01
    assert abs(forcing.lateral_bias) < 0.01
    assert forcing.rhythmic_pulse < 0.01
    assert forcing.harmonic_layer < 0.01
    assert forcing.percussive_layer < 0.01
    assert forcing.bass_layer < 0.01
    assert forcing.section_novelty < 0.01
    assert forcing.section_progress < 0.01

    limited_analysis = replace(
        synthetic_analysis,
        timeline=replace(
            timeline,
            spatial=replace(
                timeline.spatial,
                width=replace(timeline.spatial.width, validity=SignalValidity.LIMITED),
            ),
        ),
    )
    valid_width = (
        FieldConductor(synthetic_analysis)
        .advance(
            musical_time=9.0,
            delta_seconds=5.0,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing.stereo_width
    )
    limited_width = (
        FieldConductor(limited_analysis)
        .advance(
            musical_time=9.0,
            delta_seconds=5.0,
            transport_state=TransportState.PLAYING,
            transport_epoch=0,
        )
        .forcing.stereo_width
    )

    assert limited_width == pytest.approx(valid_width * 0.5, rel=0.05)
