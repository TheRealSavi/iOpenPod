"""One Application Layer entry point for complete-song music analysis."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from .audio import FFmpegDecoder
from .models import (
    AnalysisIssue,
    AnalysisIssueSeverity,
    AnalysisMode,
    AnalysisProgress,
    AnalysisRequest,
    AnalysisStage,
    TrackAnalysis,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from .audio import DecodedAudio
    from .enrichment import AnalysisEnricher, AnalysisEnrichment


class AudioDecoder(Protocol):
    def decode(
        self,
        source: Path,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> DecodedAudio: ...


class CoreMusicAnalyzer(Protocol):
    def analyze(
        self,
        audio: DecodedAudio,
        request: AnalysisRequest,
        *,
        title: str,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis: ...


class MusicAnalysisBackend(Protocol):
    def analyze(
        self,
        source: Path,
        request: AnalysisRequest | None = None,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis: ...


class WholeTrackMusicAnalyzer:
    """Decode once, run the core, then independently attempt learned enrichment."""

    def __init__(
        self,
        *,
        decoder: AudioDecoder | None = None,
        core: CoreMusicAnalyzer | None = None,
        enrichers: Sequence[AnalysisEnricher] | None = None,
    ) -> None:
        self._decoder = decoder if decoder is not None else FFmpegDecoder()
        self._core = core
        self._enrichers = tuple(enrichers) if enrichers is not None else None

    def analyze(
        self,
        source: Path,
        request: AnalysisRequest | None = None,
        *,
        checkpoint: Callable[[], None] = lambda: None,
        progress: Callable[[AnalysisProgress], None] = lambda _progress: None,
    ) -> TrackAnalysis:
        request = request or AnalysisRequest()
        audio = self._decoder.decode(
            source,
            checkpoint=checkpoint,
            progress=progress,
        )
        checkpoint()
        analysis = self._core_analyzer().analyze(
            audio,
            request,
            title=source.stem,
            checkpoint=checkpoint,
            progress=progress,
        )
        if request.mode is AnalysisMode.ENRICHED:
            analysis = self._enrich(audio, analysis, checkpoint, progress)
        checkpoint()
        progress(
            AnalysisProgress(
                1.0,
                AnalysisStage.COMPLETE,
                "Complete-song musical analysis is ready",
            )
        )
        return analysis

    def _enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis:
        for enricher in self._analysis_enrichers():
            checkpoint()
            if not enricher.available():
                analysis = replace(
                    analysis,
                    issues=(
                        *analysis.issues,
                        AnalysisIssue(
                            f"music-analysis.provider-unavailable.{_slug(enricher.provider_name)}",
                            AnalysisIssueSeverity.INFORMATION,
                            f"{enricher.provider_name} is not installed; instrument Sources are unavailable.",
                            enricher.provider_name,
                        ),
                    ),
                )
                continue
            try:
                contribution = enricher.enrich(
                    audio,
                    analysis,
                    checkpoint=checkpoint,
                    progress=progress,
                )
                analysis = _merge_analysis(analysis, contribution)
            except Exception as error:
                analysis = replace(
                    analysis,
                    issues=(
                        *analysis.issues,
                        AnalysisIssue(
                            f"music-analysis.provider-failed.{_slug(enricher.provider_name)}",
                            AnalysisIssueSeverity.FAILED_PROVIDER,
                            f"{enricher.provider_name} failed: {error}",
                            enricher.provider_name,
                        ),
                    ),
                )
                continue
        return analysis

    def _core_analyzer(self) -> CoreMusicAnalyzer:
        if self._core is None:
            from .dsp import DeterministicMusicAnalyzer

            self._core = DeterministicMusicAnalyzer()
        return self._core

    def _analysis_enrichers(self) -> tuple[AnalysisEnricher, ...]:
        if self._enrichers is None:
            from .enrichment import DemucsSourceEnricher

            self._enrichers = (DemucsSourceEnricher(),)
        return self._enrichers


def _merge_analysis(
    analysis: TrackAnalysis, contribution: AnalysisEnrichment
) -> TrackAnalysis:
    sources = (
        contribution.sources
        if contribution.replace_sources
        else (*analysis.sources, *contribution.sources)
    )
    events = tuple(
        sorted(
            (*analysis.events, *contribution.events),
            key=lambda event: (event.seconds, event.kind, event.event_id),
        )
    )
    provenance = tuple(dict.fromkeys((*analysis.provenance, *contribution.provenance)))
    return replace(
        analysis,
        sources=sources,
        events=events,
        provenance=provenance,
    )


def _slug(value: str) -> str:
    return "-".join(value.casefold().split())


__all__ = [
    "AudioDecoder",
    "CoreMusicAnalyzer",
    "MusicAnalysisBackend",
    "WholeTrackMusicAnalyzer",
]
