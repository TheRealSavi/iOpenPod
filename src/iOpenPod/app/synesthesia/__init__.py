"""Complete-song musical analysis for Synesthesia experiences."""

from importlib import import_module
from typing import TYPE_CHECKING

from .audio import AudioDecodeError, DecodedAudio, FFmpegDecoder
from .backend import (
    AudioDecoder,
    CoreMusicAnalyzer,
    MusicAnalysisBackend,
    WholeTrackMusicAnalyzer,
)
from .controller import AnalysisCancelledError, SynesthesiaController
from .models import (
    AnalysisIssue,
    AnalysisIssueSeverity,
    AnalysisMode,
    AnalysisProgress,
    AnalysisRequest,
    AnalysisStage,
    AnalysisTimeline,
    AudioMetadata,
    EnergyAnalysis,
    EnergyFrame,
    EventKind,
    FloatSeries,
    HarmonyAnalysis,
    HarmonyFrame,
    LayerAnalysis,
    LayerFrame,
    MusicalEvent,
    MusicFrame,
    MusicSection,
    Provenance,
    RhythmAnalysis,
    RhythmFrame,
    ScalarSignal,
    SectionProfile,
    SignalSample,
    SignalValidity,
    SourceAnalysis,
    SourceKind,
    SpatialAnalysis,
    SpatialFrame,
    SpectrumAnalysis,
    SpectrumFrame,
    StructureAnalysis,
    TimbreAnalysis,
    TimbreFrame,
    TimeGrid,
    TrackAnalysis,
    VectorSample,
    VectorSignal,
)

if TYPE_CHECKING:
    from .dsp import DeterministicMusicAnalyzer as DeterministicMusicAnalyzer
    from .enrichment import AnalysisEnricher as AnalysisEnricher
    from .enrichment import AnalysisEnrichment as AnalysisEnrichment
    from .enrichment import DemucsSourceEnricher as DemucsSourceEnricher

_LAZY_EXPORTS = {
    "AnalysisEnricher": (".enrichment", "AnalysisEnricher"),
    "AnalysisEnrichment": (".enrichment", "AnalysisEnrichment"),
    "DemucsSourceEnricher": (".enrichment", "DemucsSourceEnricher"),
    "DeterministicMusicAnalyzer": (".dsp", "DeterministicMusicAnalyzer"),
}


def __getattr__(name: str) -> object:
    """Load analysis implementations only when an analysis caller requests them."""

    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include deferred public implementations in package introspection."""

    return sorted(set(globals()) | _LAZY_EXPORTS.keys())


__all__ = [
    "AnalysisCancelledError",
    "AnalysisEnricher",
    "AnalysisEnrichment",
    "AnalysisIssue",
    "AnalysisIssueSeverity",
    "AnalysisMode",
    "AnalysisProgress",
    "AnalysisRequest",
    "AnalysisStage",
    "AnalysisTimeline",
    "AudioDecodeError",
    "AudioDecoder",
    "AudioMetadata",
    "CoreMusicAnalyzer",
    "DecodedAudio",
    "DemucsSourceEnricher",
    "DeterministicMusicAnalyzer",
    "EnergyAnalysis",
    "EnergyFrame",
    "EventKind",
    "FFmpegDecoder",
    "FloatSeries",
    "HarmonyAnalysis",
    "HarmonyFrame",
    "LayerAnalysis",
    "LayerFrame",
    "MusicAnalysisBackend",
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
    "SynesthesiaController",
    "TimbreAnalysis",
    "TimbreFrame",
    "TimeGrid",
    "TrackAnalysis",
    "VectorSample",
    "VectorSignal",
    "WholeTrackMusicAnalyzer",
]
