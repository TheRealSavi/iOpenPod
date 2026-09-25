"""Typed, immutable results for complete-song musical analysis."""

from __future__ import annotations

import math
import struct
import sys
from array import array
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class AnalysisMode(StrEnum):
    """How much analysis work one Job may perform."""

    STANDARD = "standard"
    ENRICHED = "enriched"


class AnalysisStage(StrEnum):
    DECODE = "decode"
    SPECTRUM = "spectrum"
    RHYTHM = "rhythm"
    MUSICAL_CONTEXT = "musical-context"
    STRUCTURE = "structure"
    SOURCES = "sources"
    COMPLETE = "complete"


class SignalValidity(StrEnum):
    VALID = "valid"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


class EventKind(StrEnum):
    ONSET = "onset"
    BEAT = "beat"
    DOWNBEAT = "downbeat"
    SECTION_BOUNDARY = "section-boundary"
    SOURCE_ENTRANCE = "source-entrance"
    SOURCE_EXIT = "source-exit"


class SourceKind(StrEnum):
    HARMONIC = "harmonic"
    PERCUSSIVE = "percussive"
    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    OTHER = "other"


class AnalysisIssueSeverity(StrEnum):
    INFORMATION = "information"
    DEGRADED = "degraded"
    FAILED_PROVIDER = "failed-provider"


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Intent for one fresh analysis Job."""

    title: str | None = None
    mode: AnalysisMode = AnalysisMode.ENRICHED

    def __post_init__(self) -> None:
        if self.title is not None and not self.title.strip():
            raise ValueError("Analysis title must contain text when supplied")


@dataclass(frozen=True, slots=True)
class AnalysisProgress:
    fraction: float
    stage: AnalysisStage
    detail: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.fraction) or not 0.0 <= self.fraction <= 1.0:
            raise ValueError("Analysis progress must be in [0, 1]")
        if not self.detail.strip():
            raise ValueError("Analysis progress requires a detail")


@dataclass(frozen=True, slots=True)
class Provenance:
    provider: str
    version: str
    method: str

    def __post_init__(self) -> None:
        if (
            not self.provider.strip()
            or not self.version.strip()
            or not self.method.strip()
        ):
            raise ValueError(
                "Analysis provenance requires provider, version, and method"
            )


@dataclass(frozen=True, slots=True)
class AnalysisIssue:
    code: str
    severity: AnalysisIssueSeverity
    message: str
    provider: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.code, self.message, self.provider)):
            raise ValueError("Analysis issues require code, message, and provider")


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """Centers of fixed-size analysis windows."""

    frame_count: int
    start_seconds: float
    step_seconds: float

    def __post_init__(self) -> None:
        if self.frame_count <= 0:
            raise ValueError("An analysis grid requires at least one frame")
        if (
            not math.isfinite(self.start_seconds)
            or self.start_seconds < 0.0
            or not math.isfinite(self.step_seconds)
            or self.step_seconds <= 0.0
        ):
            raise ValueError("Analysis-grid timing must be positive and finite")

    def time_at(self, index: int) -> float:
        if not 0 <= index < self.frame_count:
            raise IndexError("Analysis frame is outside its grid")
        return self.start_seconds + index * self.step_seconds

    def locate(self, seconds: float) -> tuple[int, int, float]:
        if not math.isfinite(seconds):
            raise ValueError("Analysis sample time must be finite")
        position = (seconds - self.start_seconds) / self.step_seconds
        left = min(self.frame_count - 1, max(0, math.floor(position)))
        right = min(self.frame_count - 1, left + 1)
        return left, right, min(1.0, max(0.0, position - left))


@dataclass(frozen=True, slots=True)
class FloatSeries:
    """Compact immutable little-endian float32 storage."""

    data: bytes
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0 or len(self.data) != self.count * 4:
            raise ValueError("Float-series storage does not match its count")

    @classmethod
    def from_values(cls, values: Iterable[float]) -> Self:
        packed = array("f", (float(value) for value in values))
        if sys.byteorder != "little":
            packed.byteswap()
        return cls(packed.tobytes(), len(packed))

    def value(self, index: int) -> float:
        if not 0 <= index < self.count:
            raise IndexError("Float-series index is outside its data")
        return float(struct.unpack_from("<f", self.data, index * 4)[0])

    def row(self, index: int, width: int) -> tuple[float, ...]:
        if width <= 0 or self.count % width:
            raise ValueError("Float-series row width is invalid")
        if not 0 <= index < self.count // width:
            raise IndexError("Float-series row is outside its data")
        return struct.unpack_from(f"<{width}f", self.data, index * width * 4)


@dataclass(frozen=True, slots=True)
class ScalarSignal:
    """One sampled measurement with independent reliability."""

    grid: TimeGrid
    values: FloatSeries
    confidence: FloatSeries
    unit: str
    validity: SignalValidity = SignalValidity.VALID
    circular: bool = False

    def __post_init__(self) -> None:
        if self.values.count != self.grid.frame_count:
            raise ValueError("Scalar values do not match their analysis grid")
        if self.confidence.count != self.grid.frame_count:
            raise ValueError("Scalar confidence does not match its analysis grid")
        if not self.unit.strip():
            raise ValueError("A scalar signal requires a unit")
        _require_finite(self.values)
        _require_unit(self.confidence, "signal confidence")

    def sample(self, seconds: float) -> SignalSample:
        left, right, blend = self.grid.locate(seconds)
        before = self.values.value(left)
        after = self.values.value(right)
        if self.circular:
            delta = (after - before + 0.5) % 1.0 - 0.5
            value = (before + delta * blend) % 1.0
        else:
            value = before + (after - before) * blend
        confidence = _lerp(
            self.confidence.value(left), self.confidence.value(right), blend
        )
        return SignalSample(value, _unit(confidence), self.unit, self.validity)


@dataclass(frozen=True, slots=True)
class VectorSignal:
    """One fixed-schema vector measurement with independent reliability."""

    grid: TimeGrid
    values: FloatSeries
    confidence: FloatSeries
    components: tuple[str, ...]
    unit: str
    validity: SignalValidity = SignalValidity.VALID
    distribution: bool = False

    def __post_init__(self) -> None:
        width = len(self.components)
        if width == 0 or any(not component.strip() for component in self.components):
            raise ValueError("A vector signal requires named components")
        if len(set(self.components)) != width:
            raise ValueError("Vector-signal component names must be unique")
        if self.values.count != self.grid.frame_count * width:
            raise ValueError("Vector values do not match their analysis grid")
        if self.confidence.count != self.grid.frame_count:
            raise ValueError("Vector confidence does not match its analysis grid")
        if not self.unit.strip():
            raise ValueError("A vector signal requires a unit")
        _require_finite(self.values)
        _require_unit(self.confidence, "signal confidence")
        if self.distribution:
            for index in range(self.grid.frame_count):
                row = self.values.row(index, width)
                if any(value < 0.0 for value in row) or sum(row) <= 0.0:
                    raise ValueError("Distribution frames require positive finite mass")

    def sample(self, seconds: float) -> VectorSample:
        left, right, blend = self.grid.locate(seconds)
        before = self.values.row(left, len(self.components))
        after = self.values.row(right, len(self.components))
        values = tuple(
            _lerp(first, second, blend)
            for first, second in zip(before, after, strict=True)
        )
        if self.distribution:
            total = sum(values)
            values = tuple(value / total for value in values)
        confidence = _lerp(
            self.confidence.value(left), self.confidence.value(right), blend
        )
        return VectorSample(
            values,
            self.components,
            _unit(confidence),
            self.unit,
            self.validity,
        )


@dataclass(frozen=True, slots=True)
class SignalSample:
    value: float
    confidence: float
    unit: str
    validity: SignalValidity


@dataclass(frozen=True, slots=True)
class VectorSample:
    values: tuple[float, ...]
    components: tuple[str, ...]
    confidence: float
    unit: str
    validity: SignalValidity

    def component(self, name: str) -> float:
        try:
            return self.values[self.components.index(name)]
        except ValueError as error:
            raise KeyError(name) from error


@dataclass(frozen=True, slots=True)
class EnergyAnalysis:
    loudness_dbfs: ScalarSignal
    relative: ScalarSignal
    crest_db: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.loudness_dbfs, self.relative, self.crest_db


@dataclass(frozen=True, slots=True)
class RhythmAnalysis:
    onset_strength: ScalarSignal
    pulse: ScalarSignal
    beat_phase: ScalarSignal
    tempo_bpm: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.onset_strength, self.pulse, self.beat_phase, self.tempo_bpm


@dataclass(frozen=True, slots=True)
class SpectrumAnalysis:
    band_levels_dbfs: VectorSignal
    band_distribution: VectorSignal
    positive_flux: VectorSignal
    centroid_hz: ScalarSignal
    bandwidth_hz: ScalarSignal
    rolloff_hz: ScalarSignal

    def signals(self) -> tuple[ScalarSignal | VectorSignal, ...]:
        return (
            self.band_levels_dbfs,
            self.band_distribution,
            self.positive_flux,
            self.centroid_hz,
            self.bandwidth_hz,
            self.rolloff_hz,
        )


@dataclass(frozen=True, slots=True)
class TimbreAnalysis:
    flatness: ScalarSignal
    contrast: ScalarSignal
    change: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.flatness, self.contrast, self.change


@dataclass(frozen=True, slots=True)
class HarmonyAnalysis:
    chroma: VectorSignal
    coherence: ScalarSignal
    change: ScalarSignal
    pitch_midi: ScalarSignal

    def signals(self) -> tuple[ScalarSignal | VectorSignal, ...]:
        return self.chroma, self.coherence, self.change, self.pitch_midi


@dataclass(frozen=True, slots=True)
class SpatialAnalysis:
    pan: ScalarSignal
    width: ScalarSignal
    correlation: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.pan, self.width, self.correlation


@dataclass(frozen=True, slots=True)
class LayerAnalysis:
    """Overlapping acoustic families; only learned Sources claim instruments."""

    bass_register: ScalarSignal
    harmonic: ScalarSignal
    percussive: ScalarSignal
    noise: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.bass_register, self.harmonic, self.percussive, self.noise


@dataclass(frozen=True, slots=True)
class StructureAnalysis:
    novelty: ScalarSignal
    section_progress: ScalarSignal

    def signals(self) -> tuple[ScalarSignal, ...]:
        return self.novelty, self.section_progress


@dataclass(frozen=True, slots=True)
class AnalysisTimeline:
    grid: TimeGrid
    window_seconds: float
    energy: EnergyAnalysis
    rhythm: RhythmAnalysis
    spectrum: SpectrumAnalysis
    timbre: TimbreAnalysis
    harmony: HarmonyAnalysis
    spatial: SpatialAnalysis
    layers: LayerAnalysis
    structure: StructureAnalysis

    def __post_init__(self) -> None:
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0.0:
            raise ValueError("Analysis windows must have positive finite duration")
        for signal in self.signals():
            if signal.grid != self.grid:
                raise ValueError("Every analysis signal must use the timeline grid")

    def signals(self) -> Iterator[ScalarSignal | VectorSignal]:
        for group in (
            self.energy,
            self.rhythm,
            self.spectrum,
            self.timbre,
            self.harmony,
            self.spatial,
            self.layers,
            self.structure,
        ):
            yield from group.signals()


@dataclass(frozen=True, slots=True)
class EnergyFrame:
    loudness_dbfs: SignalSample
    relative: SignalSample
    crest_db: SignalSample


@dataclass(frozen=True, slots=True)
class RhythmFrame:
    onset_strength: SignalSample
    pulse: SignalSample
    beat_phase: SignalSample
    tempo_bpm: SignalSample


@dataclass(frozen=True, slots=True)
class SpectrumFrame:
    band_levels_dbfs: VectorSample
    band_distribution: VectorSample
    positive_flux: VectorSample
    centroid_hz: SignalSample
    bandwidth_hz: SignalSample
    rolloff_hz: SignalSample


@dataclass(frozen=True, slots=True)
class TimbreFrame:
    flatness: SignalSample
    contrast: SignalSample
    change: SignalSample


@dataclass(frozen=True, slots=True)
class HarmonyFrame:
    chroma: VectorSample
    coherence: SignalSample
    change: SignalSample
    pitch_midi: SignalSample


@dataclass(frozen=True, slots=True)
class SpatialFrame:
    pan: SignalSample
    width: SignalSample
    correlation: SignalSample


@dataclass(frozen=True, slots=True)
class LayerFrame:
    bass_register: SignalSample
    harmonic: SignalSample
    percussive: SignalSample
    noise: SignalSample


@dataclass(frozen=True, slots=True)
class SectionProfile:
    relative_energy: float
    brightness: float
    harmonicity: float
    percussiveness: float

    def __post_init__(self) -> None:
        for name, value in (
            ("relative energy", self.relative_energy),
            ("brightness", self.brightness),
            ("harmonicity", self.harmonicity),
            ("percussiveness", self.percussiveness),
        ):
            _validate_unit(value, f"Section {name}")


@dataclass(frozen=True, slots=True)
class MusicSection:
    section_id: str
    label: str
    start_seconds: float
    end_seconds: float
    confidence: float
    profile: SectionProfile

    def __post_init__(self) -> None:
        if not self.section_id.strip() or not self.label.strip():
            raise ValueError("A Section requires an identity and label")
        if (
            not math.isfinite(self.start_seconds)
            or not math.isfinite(self.end_seconds)
            or self.start_seconds < 0.0
            or self.end_seconds <= self.start_seconds
        ):
            raise ValueError("A Section requires a positive finite span")
        _validate_unit(self.confidence, "Section confidence")


@dataclass(frozen=True, slots=True)
class MusicalEvent:
    event_id: str
    kind: EventKind
    seconds: float
    strength: float
    confidence: float
    bands: VectorSample | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("A musical event requires an identity")
        if not math.isfinite(self.seconds) or self.seconds < 0.0:
            raise ValueError("A musical event requires a non-negative finite time")
        _validate_unit(self.strength, "Musical event strength")
        _validate_unit(self.confidence, "Musical event confidence")


@dataclass(frozen=True, slots=True)
class SourceAnalysis:
    """One separated or acoustic source family with honest provenance."""

    source_id: str
    kind: SourceKind
    label: str
    confidence: float
    presence: ScalarSignal
    loudness_dbfs: ScalarSignal
    onset_strength: ScalarSignal
    centroid_hz: ScalarSignal
    pan: ScalarSignal
    width: ScalarSignal
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.label.strip():
            raise ValueError("A Source requires an identity and label")
        _validate_unit(self.confidence, "Source confidence")
        grid = self.presence.grid
        if any(
            signal.grid != grid
            for signal in (
                self.loudness_dbfs,
                self.onset_strength,
                self.centroid_hz,
                self.pan,
                self.width,
            )
        ):
            raise ValueError("Every Source signal must use one grid")


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    title: str
    duration_seconds: float
    sample_rate_hz: int
    channels: int

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Analyzed audio requires a title")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0.0:
            raise ValueError("Analyzed audio requires a positive finite duration")
        if self.sample_rate_hz <= 0 or self.channels <= 0:
            raise ValueError("Analyzed audio format is invalid")


@dataclass(frozen=True, slots=True)
class MusicFrame:
    seconds: float
    energy: EnergyFrame
    rhythm: RhythmFrame
    spectrum: SpectrumFrame
    timbre: TimbreFrame
    harmony: HarmonyFrame
    spatial: SpatialFrame
    layers: LayerFrame
    section: MusicSection
    section_novelty: SignalSample
    section_progress: SignalSample


@dataclass(frozen=True, slots=True)
class TrackAnalysis:
    """The single public result of a complete-song analysis Job."""

    metadata: AudioMetadata
    timeline: AnalysisTimeline
    sections: tuple[MusicSection, ...]
    events: tuple[MusicalEvent, ...]
    sources: tuple[SourceAnalysis, ...]
    issues: tuple[AnalysisIssue, ...]
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("Track analysis requires at least one Section")
        _require_unique((section.section_id for section in self.sections), "Section")
        _require_unique((event.event_id for event in self.events), "event")
        _require_unique((source.source_id for source in self.sources), "Source")
        if not self.provenance:
            raise ValueError("Track analysis requires provider provenance")
        _require_unique(self.provenance, "provenance")
        if tuple(sorted(self.events, key=lambda event: event.seconds)) != self.events:
            raise ValueError("Musical events must be ordered by time")
        if (
            tuple(sorted(self.sections, key=lambda section: section.start_seconds))
            != self.sections
        ):
            raise ValueError("Sections must be ordered by time")
        tolerance = self.timeline.window_seconds
        if not math.isclose(self.sections[0].start_seconds, 0.0, abs_tol=tolerance):
            raise ValueError("Sections must begin with the Track")
        if not math.isclose(
            self.sections[-1].end_seconds,
            self.metadata.duration_seconds,
            abs_tol=tolerance,
        ):
            raise ValueError("Sections must cover the complete Track")
        for first, second in zip(self.sections, self.sections[1:], strict=False):
            if not math.isclose(
                first.end_seconds, second.start_seconds, abs_tol=tolerance
            ):
                raise ValueError("Sections must be contiguous")
        if any(event.seconds > self.metadata.duration_seconds for event in self.events):
            raise ValueError("A musical event lies beyond its Track")
        source_ids = {source.source_id for source in self.sources}
        if any(
            event.source_id is not None and event.source_id not in source_ids
            for event in self.events
        ):
            raise ValueError("A musical event names an unknown Source")
        if any(source.presence.grid != self.timeline.grid for source in self.sources):
            raise ValueError("Every Source must use the Track timeline grid")

    def section_at(self, seconds: float) -> MusicSection:
        bounded = min(self.metadata.duration_seconds, max(0.0, seconds))
        return next(
            (
                section
                for section in self.sections
                if section.start_seconds <= bounded < section.end_seconds
            ),
            self.sections[-1],
        )

    def events_between(
        self, start_seconds: float, end_seconds: float
    ) -> tuple[MusicalEvent, ...]:
        if end_seconds < start_seconds:
            raise ValueError("Event interval ends before it starts")
        return tuple(
            event
            for event in self.events
            if start_seconds <= event.seconds <= end_seconds
        )

    def sample(self, seconds: float) -> MusicFrame:
        bounded = min(self.metadata.duration_seconds, max(0.0, seconds))
        timeline = self.timeline
        loudness = timeline.energy.loudness_dbfs.sample(bounded)
        relative = timeline.energy.relative.sample(bounded)
        crest = timeline.energy.crest_db.sample(bounded)
        onset = timeline.rhythm.onset_strength.sample(bounded)
        pulse = timeline.rhythm.pulse.sample(bounded)
        phase = timeline.rhythm.beat_phase.sample(bounded)
        tempo = timeline.rhythm.tempo_bpm.sample(bounded)
        return MusicFrame(
            seconds=bounded,
            energy=EnergyFrame(loudness, relative, crest),
            rhythm=RhythmFrame(onset, pulse, phase, tempo),
            spectrum=SpectrumFrame(
                timeline.spectrum.band_levels_dbfs.sample(bounded),
                timeline.spectrum.band_distribution.sample(bounded),
                timeline.spectrum.positive_flux.sample(bounded),
                timeline.spectrum.centroid_hz.sample(bounded),
                timeline.spectrum.bandwidth_hz.sample(bounded),
                timeline.spectrum.rolloff_hz.sample(bounded),
            ),
            timbre=TimbreFrame(
                timeline.timbre.flatness.sample(bounded),
                timeline.timbre.contrast.sample(bounded),
                timeline.timbre.change.sample(bounded),
            ),
            harmony=HarmonyFrame(
                timeline.harmony.chroma.sample(bounded),
                timeline.harmony.coherence.sample(bounded),
                timeline.harmony.change.sample(bounded),
                timeline.harmony.pitch_midi.sample(bounded),
            ),
            spatial=SpatialFrame(
                timeline.spatial.pan.sample(bounded),
                timeline.spatial.width.sample(bounded),
                timeline.spatial.correlation.sample(bounded),
            ),
            layers=LayerFrame(
                timeline.layers.bass_register.sample(bounded),
                timeline.layers.harmonic.sample(bounded),
                timeline.layers.percussive.sample(bounded),
                timeline.layers.noise.sample(bounded),
            ),
            section=self.section_at(bounded),
            section_novelty=timeline.structure.novelty.sample(bounded),
            section_progress=timeline.structure.section_progress.sample(bounded),
        )


def _lerp(before: float, after: float, blend: float) -> float:
    return before + (after - before) * blend


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _validate_unit(value: float, label: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be finite and in [0, 1]")


def _require_finite(series: FloatSeries) -> None:
    if any(not math.isfinite(series.value(index)) for index in range(series.count)):
        raise ValueError("Analysis signal contains a non-finite value")


def _require_unit(series: FloatSeries, label: str) -> None:
    for index in range(series.count):
        _validate_unit(series.value(index), label)


def _require_unique(values: Iterable[object], label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"Duplicate {label} identity")


__all__ = [
    "AnalysisIssue",
    "AnalysisIssueSeverity",
    "AnalysisMode",
    "AnalysisProgress",
    "AnalysisRequest",
    "AnalysisStage",
    "AnalysisTimeline",
    "AudioMetadata",
    "EnergyAnalysis",
    "EnergyFrame",
    "EventKind",
    "FloatSeries",
    "HarmonyAnalysis",
    "HarmonyFrame",
    "LayerAnalysis",
    "LayerFrame",
    "MusicFrame",
    "MusicSection",
    "MusicalEvent",
    "Provenance",
    "RhythmAnalysis",
    "RhythmFrame",
    "ScalarSignal",
    "SectionProfile",
    "SignalSample",
    "SignalValidity",
    "SourceAnalysis",
    "SourceKind",
    "SpatialAnalysis",
    "SpatialFrame",
    "SpectrumAnalysis",
    "SpectrumFrame",
    "StructureAnalysis",
    "TimbreAnalysis",
    "TimbreFrame",
    "TimeGrid",
    "TrackAnalysis",
    "VectorSample",
    "VectorSignal",
]
