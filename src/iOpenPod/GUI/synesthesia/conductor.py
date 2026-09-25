"""Translate complete-song analysis into expressive field forcing."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Final

from iOpenPod.app.synesthesia import (
    EventKind,
    MusicalEvent,
    MusicFrame,
    SignalSample,
    SignalValidity,
    SourceKind,
    TrackAnalysis,
    VectorSample,
)

from .persistent_world import (
    FieldForcing,
    FieldImpulse,
    FieldImpulseCharacter,
    TransportState,
    Vec3,
)

_CLOCK_EPSILON: Final = 1e-6
_IMPACT_MINIMUM_AMPLITUDE: Final = 0.075
_ONSET_MINIMUM_AMPLITUDE: Final = 0.16
_ONSET_CLUSTER_SECONDS: Final = 0.11
_ONSET_REFRACTORY_SECONDS: Final = 3.6
_BEAT_LASER_MINIMUM_STRENGTH: Final = 0.78
_BEAT_LASER_MINIMUM_CONFIDENCE: Final = 0.62
_BEAT_LASER_REFRACTORY_SECONDS: Final = 5.0
_BEAT_LASER_DOWNBEAT_GUARD_SECONDS: Final = 0.55
_LIMITED_EVIDENCE_WEIGHT: Final = 0.5
_IMPACT_KINDS: Final = frozenset(
    (
        EventKind.ONSET,
        EventKind.BEAT,
        EventKind.DOWNBEAT,
        EventKind.SECTION_BOUNDARY,
        EventKind.SOURCE_ENTRANCE,
    )
)


@dataclass(frozen=True, slots=True)
class ConductedField:
    """One sampled forcing plus the musical events crossed this frame."""

    musical_time: float
    transport_state: TransportState
    transport_epoch: int
    forcing: FieldForcing
    crossed_events: tuple[MusicalEvent, ...] = ()

    @property
    def conditions(self) -> FieldForcing:
        return self.forcing


@dataclass(slots=True)
class _ForceChannel:
    attack_seconds: float
    release_seconds: float
    maximum_slew_per_second: float
    value: float

    def advance(self, target: float, delta_seconds: float) -> float:
        target = _unit(target)
        if delta_seconds <= 0.0:
            return self.value
        time_constant = (
            self.attack_seconds if target >= self.value else self.release_seconds
        )
        delta = (target - self.value) * -math.expm1(-delta_seconds / time_constant)
        maximum_delta = self.maximum_slew_per_second * delta_seconds
        self.value = _unit(self.value + min(maximum_delta, max(-maximum_delta, delta)))
        return self.value


@dataclass(slots=True)
class _SignedForceChannel:
    response_seconds: float
    maximum_slew_per_second: float
    value: float = 0.0

    def advance(self, target: float, delta_seconds: float) -> float:
        target = _signed_unit(target)
        if delta_seconds <= 0.0:
            return self.value
        delta = (target - self.value) * -math.expm1(
            -delta_seconds / self.response_seconds
        )
        maximum_delta = self.maximum_slew_per_second * delta_seconds
        self.value = _signed_unit(
            self.value + min(maximum_delta, max(-maximum_delta, delta))
        )
        return self.value


@dataclass(slots=True)
class _CircularForceChannel:
    response_seconds: float
    value: float

    def advance(self, target: float, delta_seconds: float) -> float:
        target %= 1.0
        if delta_seconds <= 0.0:
            return self.value
        blend = -math.expm1(-delta_seconds / self.response_seconds)
        delta = (target - self.value + 0.5) % 1.0 - 0.5
        self.value = (self.value + delta * blend) % 1.0
        return self.value


class FieldConductor:
    """Map independent musical dimensions into renderer-neutral field controls."""

    def __init__(self, analysis: TrackAnalysis) -> None:
        self._analysis = analysis
        self._seed = analysis_seed(analysis)
        self._transport_epoch: int | None = None
        self._transport_state: TransportState | None = None
        self._musical_time: float | None = None
        self._delivered_event_ids: set[str] = set()
        self._admitted_onset_event_ids = _plan_onset_event_ids(analysis.events)
        self._admitted_beat_event_ids = _plan_beat_event_ids(analysis.events)
        self._activity = _ForceChannel(0.07, 0.62, 4.5, 0.08)
        self._mass = _ForceChannel(0.11, 0.95, 2.7, 0.0)
        self._excitation = _ForceChannel(0.025, 0.26, 8.5, 0.02)
        self._coherence = _ForceChannel(0.34, 0.78, 1.6, 0.5)
        self._palette = _CircularForceChannel(0.72, 0.58)
        self._palette_spread = _ForceChannel(0.18, 0.72, 2.4, 0.35)
        self._brightness = _ForceChannel(0.12, 0.58, 2.8, 0.35)
        self._flux = _ForceChannel(0.035, 0.24, 7.5, 0.0)
        self._noise = _ForceChannel(0.09, 0.48, 3.0, 0.0)
        self._width = _ForceChannel(0.22, 0.64, 2.0, 0.0)
        self._pan = _SignedForceChannel(0.20, 2.6)
        self._harmonic = _ForceChannel(0.14, 0.52, 3.0, 0.0)
        self._percussive = _ForceChannel(0.035, 0.30, 6.0, 0.0)
        self._vocals = _ForceChannel(0.16, 0.68, 2.6, 0.0)
        self._bass_source = _ForceChannel(0.10, 0.60, 3.2, 0.0)
        self._novelty = _ForceChannel(0.035, 0.50, 6.0, 0.0)

    def advance(
        self,
        *,
        musical_time: float,
        delta_seconds: float,
        transport_state: TransportState,
        transport_epoch: int,
    ) -> ConductedField:
        _validate_advance(
            musical_time=musical_time,
            delta_seconds=delta_seconds,
            transport_state=transport_state,
            transport_epoch=transport_epoch,
        )
        bounded_time = min(self._analysis.metadata.duration_seconds, musical_time)
        previous_epoch = self._transport_epoch
        previous_state = self._transport_state
        crossed = self._crossed_events(
            musical_time=bounded_time,
            transport_state=transport_state,
            transport_epoch=transport_epoch,
        )
        active_delta = (
            delta_seconds
            if transport_state is TransportState.PLAYING
            and (
                previous_epoch is None
                or (
                    previous_epoch == transport_epoch
                    and previous_state is TransportState.PLAYING
                )
            )
            else 0.0
        )
        frame = self._analysis.sample(bounded_time)
        targets = _targets(self._analysis, frame, self._seed)
        admitted_events = self._admit_impact_events(crossed)
        impacts = tuple(
            impulse
            for event in admitted_events
            if (impulse := self._field_impulse(event, transport_epoch)) is not None
        )
        dominant_impacts = tuple(
            sorted(impacts, key=lambda item: item.amplitude, reverse=True)[:8]
        )
        forcing = FieldForcing(
            activity=self._activity.advance(targets.activity, active_delta),
            low_frequency_mass=self._mass.advance(
                targets.low_frequency_mass, active_delta
            ),
            fine_excitation=self._excitation.advance(
                targets.fine_excitation, active_delta
            ),
            harmonic_coherence=self._coherence.advance(
                targets.harmonic_coherence, active_delta
            ),
            palette_hue=self._palette.advance(targets.palette_hue, active_delta),
            palette_spread=self._palette_spread.advance(
                targets.palette_spread, active_delta
            ),
            brightness=self._brightness.advance(targets.brightness, active_delta),
            spectral_flux=self._flux.advance(targets.spectral_flux, active_delta),
            timbral_noise=self._noise.advance(targets.timbral_noise, active_delta),
            stereo_width=self._width.advance(targets.stereo_width, active_delta),
            lateral_bias=self._pan.advance(targets.lateral_bias, active_delta),
            rhythmic_pulse=targets.rhythmic_pulse,
            beat_phase=targets.beat_phase,
            harmonic_layer=self._harmonic.advance(targets.harmonic_layer, active_delta),
            percussive_layer=self._percussive.advance(
                targets.percussive_layer, active_delta
            ),
            vocal_layer=self._vocals.advance(targets.vocal_layer, active_delta),
            bass_layer=self._bass_source.advance(targets.bass_layer, active_delta),
            section_novelty=self._novelty.advance(
                targets.section_novelty, active_delta
            ),
            section_progress=targets.section_progress,
            section_identity=targets.section_identity,
            section_energy=targets.section_energy,
            impulses=dominant_impacts,
        )
        return ConductedField(
            musical_time=bounded_time,
            transport_state=transport_state,
            transport_epoch=transport_epoch,
            forcing=forcing,
            crossed_events=crossed,
        )

    def _crossed_events(
        self,
        *,
        musical_time: float,
        transport_state: TransportState,
        transport_epoch: int,
    ) -> tuple[MusicalEvent, ...]:
        previous_epoch = self._transport_epoch
        previous_state = self._transport_state
        previous_time = self._musical_time
        if previous_epoch is not None:
            if transport_epoch < previous_epoch:
                raise ValueError("Transport Epoch cannot move backward")
            if transport_epoch == previous_epoch and previous_time is not None:
                if musical_time + _CLOCK_EPSILON < previous_time:
                    raise ValueError(
                        "Backward musical movement requires a new Transport Epoch"
                    )
                if (
                    previous_state is TransportState.PAUSED
                    and abs(musical_time - previous_time) > _CLOCK_EPSILON
                ):
                    raise ValueError(
                        "Paused transport movement requires a new Transport Epoch"
                    )

        new_epoch = previous_epoch is not None and transport_epoch > previous_epoch
        if previous_epoch is None or new_epoch:
            self._delivered_event_ids.clear()
        candidates: tuple[MusicalEvent, ...] = ()
        if transport_state is TransportState.PLAYING and not new_epoch:
            start = musical_time if previous_time is None else previous_time
            candidates = tuple(
                event
                for event in self._analysis.events_between(start, musical_time)
                if event.kind in _IMPACT_KINDS
                and (previous_time is None or event.seconds > start + _CLOCK_EPSILON)
            )
        crossed = tuple(
            event
            for event in candidates
            if event.event_id not in self._delivered_event_ids
        )
        self._delivered_event_ids.update(event.event_id for event in crossed)
        self._transport_epoch = transport_epoch
        self._transport_state = transport_state
        self._musical_time = musical_time
        return crossed

    def _admit_impact_events(
        self,
        crossed: tuple[MusicalEvent, ...],
    ) -> tuple[MusicalEvent, ...]:
        """Edit dense evidence into legible, hierarchically distinct events."""

        admitted = [
            event
            for event in crossed
            if event.kind not in (EventKind.ONSET, EventKind.BEAT)
        ]
        admitted.extend(
            event
            for event in crossed
            if event.kind is EventKind.ONSET
            and event.event_id in self._admitted_onset_event_ids
        )

        admitted.extend(
            event
            for event in crossed
            if event.kind is EventKind.BEAT
            and event.event_id in self._admitted_beat_event_ids
        )
        return tuple(sorted(admitted, key=lambda event: event.seconds))

    def _field_impulse(
        self, event: MusicalEvent, transport_epoch: int
    ) -> FieldImpulse | None:
        amplitude = _event_amplitude(event)
        minimum_amplitude = (
            _ONSET_MINIMUM_AMPLITUDE
            if event.kind is EventKind.ONSET
            else _IMPACT_MINIMUM_AMPLITUDE
        )
        if amplitude < minimum_amplitude:
            return None
        low = high = 0.0
        if event.bands is not None:
            low = sum(
                _component(event, name) for name in ("sub-bass", "bass", "low-mid")
            )
            high = sum(
                _component(event, name)
                for name in ("upper-mid", "presence", "brilliance")
            )
        source = next(
            (
                candidate
                for candidate in self._analysis.sources
                if candidate.source_id == event.source_id
            ),
            None,
        )
        pan = source.pan.sample(event.seconds) if source is not None else None
        x = (
            pan.value * 0.82
            if pan is not None and pan.confidence >= 0.35
            else 0.72 * _stable_signed(self._seed, event.event_id, "x")
        )
        y = _signed_unit(high - low) * 0.58
        y += 0.11 * _stable_signed(self._seed, event.event_id, "y")
        z = 0.64 * _stable_signed(self._seed, event.event_id, "z")
        is_boundary = event.kind is EventKind.SECTION_BOUNDARY
        if is_boundary:
            x *= 0.35
            y *= 0.35
            z *= 0.35
        return FieldImpulse(
            impulse_id=f"analysis-{self._seed}:epoch-{transport_epoch}:{event.event_id}",
            musical_event_id=event.event_id,
            transport_epoch=transport_epoch,
            origin=Vec3(x, y, z),
            amplitude=amplitude,
            character=_impulse_character(event.kind),
            speed=0.72 + 1.46 * high + (0.38 if is_boundary else 0.0),
            decay_seconds=1.15 + 2.45 * low + (1.2 if is_boundary else 0.0),
        )


def _targets(
    analysis: TrackAnalysis,
    frame: MusicFrame,
    seed: int,
) -> FieldForcing:
    calibrated_activity = _reliability(frame.energy.loudness_dbfs) * _dbfs_unit(
        frame.energy.loudness_dbfs.value,
        floor=-72.0,
        ceiling=-9.0,
    )
    activity = _unit(
        0.50 * calibrated_activity
        + 0.38 * _evidence(frame.energy.relative)
        + 0.12 * _evidence(frame.layers.percussive)
    )
    bands = frame.spectrum.band_distribution
    band_reliability = _reliability(bands)
    low_share = band_reliability * sum(
        bands.component(name) for name in ("sub-bass", "bass", "low-mid")
    )
    high_share = (
        sum(bands.component(name) for name in ("upper-mid", "presence", "brilliance"))
        * band_reliability
    )
    bass_level = frame.spectrum.band_levels_dbfs
    mass = _unit(
        0.44
        * _reliability(bass_level)
        * _dbfs_unit(
            bass_level.component("bass"),
            floor=-72.0,
            ceiling=-12.0,
        )
        + 0.34 * low_share
        + 0.22 * _evidence(frame.layers.bass_register)
    )
    flux = _unit(
        _reliability(frame.spectrum.positive_flux)
        * sum(frame.spectrum.positive_flux.values)
        / 4.0
    )
    excitation = _unit(
        0.22 * high_share
        + 0.20 * flux
        + 0.19 * _evidence(frame.rhythm.onset_strength)
        + 0.13 * _evidence(frame.rhythm.pulse)
        + 0.12 * _evidence(frame.timbre.change)
        + 0.08 * _evidence(frame.section_novelty)
        + 0.06 * _evidence(frame.layers.noise)
    )
    coherence = _unit(_evidence(frame.harmony.coherence, neutral=0.5))
    chroma_hue, tonal_focus = _chroma_color(frame)
    section_hue = _stable_fraction(seed, frame.section.section_id, "palette")
    palette_hue = _circular_mix(
        section_hue,
        chroma_hue,
        _reliability(frame.harmony.chroma) * (0.34 + 0.46 * coherence),
    )
    centroid = frame.spectrum.centroid_hz
    brightness = _unit(
        0.55
        * _reliability(centroid)
        * math.log2(max(40.0, centroid.value) / 40.0)
        / 9.0
        + 0.45 * high_share
    )
    sources = {
        kind: _source_presence(analysis, kind, frame.seconds)
        for kind in (SourceKind.VOCALS, SourceKind.DRUMS, SourceKind.BASS)
    }
    section_index = analysis.sections.index(frame.section)
    section_identity = (
        section_index / max(1, len(analysis.sections) - 1)
        if len(analysis.sections) > 1
        else 0.0
    )
    beat_phase = frame.rhythm.beat_phase
    return FieldForcing(
        activity=max(activity, 0.38 * sources[SourceKind.VOCALS]),
        low_frequency_mass=_unit(0.78 * mass + 0.22 * sources[SourceKind.BASS]),
        fine_excitation=_unit(0.78 * excitation + 0.22 * sources[SourceKind.DRUMS]),
        harmonic_coherence=coherence,
        palette_hue=palette_hue,
        palette_spread=_unit(0.22 + 0.48 * (1.0 - tonal_focus) + 0.30 * flux),
        brightness=brightness,
        spectral_flux=flux,
        timbral_noise=_unit(
            0.62 * _evidence(frame.timbre.flatness)
            + 0.38 * _evidence(frame.layers.noise)
        ),
        stereo_width=_unit(_evidence(frame.spatial.width)),
        lateral_bias=_evidence(frame.spatial.pan),
        rhythmic_pulse=_unit(_evidence(frame.rhythm.pulse)),
        beat_phase=(beat_phase.value % 1.0 if _reliability(beat_phase) > 0.0 else 0.0),
        harmonic_layer=_evidence(frame.layers.harmonic),
        percussive_layer=_evidence(frame.layers.percussive),
        vocal_layer=sources[SourceKind.VOCALS],
        bass_layer=max(_evidence(frame.layers.bass_register), sources[SourceKind.BASS]),
        section_novelty=_evidence(frame.section_novelty),
        section_progress=_evidence(frame.section_progress),
        section_identity=section_identity,
        section_energy=(
            frame.section.profile.relative_energy * _reliability(frame.energy.relative)
        ),
    )


def _chroma_color(frame: MusicFrame) -> tuple[float, float]:
    values = frame.harmony.chroma.values
    x = sum(
        value * math.cos(2.0 * math.pi * index / len(values))
        for index, value in enumerate(values)
    )
    y = sum(
        value * math.sin(2.0 * math.pi * index / len(values))
        for index, value in enumerate(values)
    )
    hue = math.atan2(y, x) / (2.0 * math.pi) % 1.0
    tonal_focus = _unit(math.hypot(x, y))
    return hue, _evidence_reliability(
        tonal_focus,
        _reliability(frame.harmony.chroma),
        neutral=0.5,
    )


def _source_presence(
    analysis: TrackAnalysis,
    kind: SourceKind,
    seconds: float,
) -> float:
    source = next((item for item in analysis.sources if item.kind is kind), None)
    if source is None:
        return 0.0
    sample = source.presence.sample(seconds)
    confidence = sample.confidence * source.confidence
    if sample.validity is SignalValidity.UNAVAILABLE:
        return 0.0
    if sample.validity is SignalValidity.LIMITED:
        confidence *= _LIMITED_EVIDENCE_WEIGHT
    return _unit(sample.value * confidence)


def _evidence(sample: SignalSample, *, neutral: float = 0.0) -> float:
    return _evidence_reliability(sample.value, _reliability(sample), neutral=neutral)


def _evidence_reliability(value: float, reliability: float, *, neutral: float) -> float:
    return neutral + (value - neutral) * reliability


def _reliability(sample: SignalSample | VectorSample) -> float:
    if sample.validity is SignalValidity.UNAVAILABLE:
        return 0.0
    confidence = sample.confidence
    if sample.validity is SignalValidity.LIMITED:
        confidence *= _LIMITED_EVIDENCE_WEIGHT
    return _unit(confidence)


def _component(event: MusicalEvent, name: str) -> float:
    assert event.bands is not None
    return event.bands.component(name)


def _plan_onset_event_ids(events: tuple[MusicalEvent, ...]) -> frozenset[str]:
    """Select salient onset representatives independently of render cadence."""

    candidates = tuple(
        event
        for event in events
        if event.kind is EventKind.ONSET
        and _event_amplitude(event) >= _ONSET_MINIMUM_AMPLITUDE
    )
    clusters: list[list[MusicalEvent]] = []
    for event in candidates:
        if (
            not clusters
            or event.seconds - clusters[-1][-1].seconds > _ONSET_CLUSTER_SECONDS
        ):
            clusters.append([event])
        else:
            clusters[-1].append(event)

    cluster_peaks = (max(cluster, key=_event_amplitude) for cluster in clusters)
    ranked = sorted(
        cluster_peaks,
        key=lambda event: (-_event_amplitude(event), event.seconds, event.event_id),
    )
    selected: list[MusicalEvent] = []
    for event in ranked:
        if all(
            abs(event.seconds - prior.seconds) >= _ONSET_REFRACTORY_SECONDS
            for prior in selected
        ):
            selected.append(event)
    return frozenset(event.event_id for event in selected)


def _plan_beat_event_ids(events: tuple[MusicalEvent, ...]) -> frozenset[str]:
    """Select rare beat accents with whole-timeline downbeat awareness."""

    downbeat_times = tuple(
        event.seconds for event in events if event.kind is EventKind.DOWNBEAT
    )
    ranked = sorted(
        (
            event
            for event in events
            if event.kind is EventKind.BEAT
            and event.strength >= _BEAT_LASER_MINIMUM_STRENGTH
            and event.confidence >= _BEAT_LASER_MINIMUM_CONFIDENCE
            and all(
                abs(event.seconds - downbeat) >= _BEAT_LASER_DOWNBEAT_GUARD_SECONDS
                for downbeat in downbeat_times
            )
        ),
        key=lambda event: (-_event_amplitude(event), event.seconds, event.event_id),
    )
    selected: list[MusicalEvent] = []
    for event in ranked:
        if all(
            abs(event.seconds - prior.seconds) >= _BEAT_LASER_REFRACTORY_SECONDS
            for prior in selected
        ):
            selected.append(event)
    return frozenset(event.event_id for event in selected)


def _event_amplitude(event: MusicalEvent) -> float:
    kind_weight = {
        EventKind.ONSET: 0.72,
        EventKind.BEAT: 0.55,
        EventKind.DOWNBEAT: 0.92,
        EventKind.SECTION_BOUNDARY: 1.0,
        EventKind.SOURCE_ENTRANCE: 0.82,
    }.get(event.kind, 0.0)
    return _unit(event.strength * event.confidence * kind_weight)


def _impulse_character(kind: EventKind) -> FieldImpulseCharacter:
    return {
        EventKind.ONSET: FieldImpulseCharacter.BURST,
        EventKind.BEAT: FieldImpulseCharacter.LASER,
        EventKind.DOWNBEAT: FieldImpulseCharacter.LASER,
        EventKind.SECTION_BOUNDARY: FieldImpulseCharacter.RIFT,
        EventKind.SOURCE_ENTRANCE: FieldImpulseCharacter.SOURCE_FLARE,
    }[kind]


def analysis_seed(analysis: TrackAnalysis) -> int:
    digest = hashlib.blake2s(
        (
            f"{analysis.metadata.title}:{analysis.metadata.duration_seconds}:"
            f"{analysis.metadata.sample_rate_hz}"
        ).encode(),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, "little")


def _validate_advance(
    *,
    musical_time: float,
    delta_seconds: float,
    transport_state: TransportState,
    transport_epoch: int,
) -> None:
    if type(transport_state) is not TransportState:
        raise ValueError("transport_state must be a TransportState")
    if not math.isfinite(musical_time) or musical_time < 0.0:
        raise ValueError("musical_time must be non-negative and finite")
    if not math.isfinite(delta_seconds) or delta_seconds < 0.0:
        raise ValueError("delta_seconds must be non-negative and finite")
    if type(transport_epoch) is not int or transport_epoch < 0:
        raise ValueError("transport_epoch must be a non-negative integer")


def _dbfs_unit(value: float, *, floor: float, ceiling: float) -> float:
    return _unit((value - floor) / (ceiling - floor))


def _circular_mix(first: float, second: float, blend: float) -> float:
    delta = (second - first + 0.5) % 1.0 - 0.5
    return (first + delta * _unit(blend)) % 1.0


def _stable_fraction(seed: int, identity: str, axis: str) -> float:
    digest = hashlib.blake2s(
        f"{seed}:{identity}:{axis}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / float((1 << 64) - 1)


def _stable_signed(seed: int, identity: str, axis: str) -> float:
    return _stable_fraction(seed, identity, axis) * 2.0 - 1.0


def _signed_unit(value: float) -> float:
    return min(1.0, max(-1.0, value))


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


__all__ = [
    "ConductedField",
    "FieldConductor",
    "analysis_seed",
]
