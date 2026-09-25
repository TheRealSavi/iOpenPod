from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app.synesthesia import (
    AnalysisEnrichment,
    AnalysisIssueSeverity,
    AnalysisMode,
    AnalysisProgress,
    AnalysisRequest,
    AnalysisStage,
    SourceKind,
    WholeTrackMusicAnalyzer,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.synesthesia import (
        DecodedAudio,
        SourceAnalysis,
        TrackAnalysis,
    )


@dataclass
class _Decoder:
    audio: DecodedAudio

    def decode(
        self,
        source: Path,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> DecodedAudio:
        del source, progress
        checkpoint()
        return self.audio


@dataclass
class _Core:
    analysis: TrackAnalysis

    def analyze(
        self,
        audio: DecodedAudio,
        request: AnalysisRequest,
        *,
        title: str,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis:
        del audio, request, title, progress
        checkpoint()
        return self.analysis


class _Unavailable:
    provider_name = "Optional model"

    def available(self) -> bool:
        return False

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment:
        del audio, analysis, checkpoint, progress
        raise AssertionError("unavailable enrichers must not run")


class _Failing:
    provider_name = "Broken model"

    def available(self) -> bool:
        return True

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment:
        del audio, analysis, checkpoint, progress
        raise RuntimeError("bad weights")


@dataclass
class _Invalid:
    source: SourceAnalysis
    provider_name: str = "Invalid model"

    def available(self) -> bool:
        return True

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment:
        del audio, analysis, checkpoint, progress
        return AnalysisEnrichment(sources=(self.source,))


@dataclass
class _Replacing:
    source: SourceAnalysis
    calls: int = 0
    provider_name: str = "Test separator"

    def available(self) -> bool:
        return True

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment:
        del audio, analysis
        self.calls += 1
        checkpoint()
        progress(AnalysisProgress(0.9, AnalysisStage.SOURCES, "Testing enrichment"))
        return AnalysisEnrichment(sources=(self.source,), replace_sources=True)


def test_standard_mode_skips_optional_enrichment(
    synthetic_audio: DecodedAudio,
    synthetic_analysis: TrackAnalysis,
) -> None:
    enricher = _Replacing(
        replace(
            synthetic_analysis.sources[0],
            source_id="vocals",
            kind=SourceKind.VOCALS,
            label="Vocals",
        )
    )
    backend = WholeTrackMusicAnalyzer(
        decoder=_Decoder(synthetic_audio),
        core=_Core(synthetic_analysis),
        enrichers=(enricher,),
    )

    result = backend.analyze(
        Path("song.wav"),
        AnalysisRequest(mode=AnalysisMode.STANDARD),
    )

    assert result is synthetic_analysis
    assert enricher.calls == 0


def test_enrichment_replaces_acoustic_sources_and_completes_progress(
    synthetic_audio: DecodedAudio,
    synthetic_analysis: TrackAnalysis,
) -> None:
    vocal = replace(
        synthetic_analysis.sources[0],
        source_id="vocals",
        kind=SourceKind.VOCALS,
        label="Vocals",
    )
    enricher = _Replacing(vocal)
    updates: list[AnalysisProgress] = []
    backend = WholeTrackMusicAnalyzer(
        decoder=_Decoder(synthetic_audio),
        core=_Core(synthetic_analysis),
        enrichers=(enricher,),
    )

    result = backend.analyze(Path("song.wav"), progress=updates.append)

    assert result.sources == (vocal,)
    assert enricher.calls == 1
    assert updates[-1].stage is AnalysisStage.COMPLETE
    assert updates[-1].fraction == 1.0


def test_optional_provider_absence_and_failure_are_typed_issues(
    synthetic_audio: DecodedAudio,
    synthetic_analysis: TrackAnalysis,
) -> None:
    backend = WholeTrackMusicAnalyzer(
        decoder=_Decoder(synthetic_audio),
        core=_Core(synthetic_analysis),
        enrichers=(
            _Unavailable(),
            _Invalid(synthetic_analysis.sources[0]),
            _Failing(),
        ),
    )

    result = backend.analyze(Path("song.wav"))

    assert [issue.severity for issue in result.issues[-3:]] == [
        AnalysisIssueSeverity.INFORMATION,
        AnalysisIssueSeverity.FAILED_PROVIDER,
        AnalysisIssueSeverity.FAILED_PROVIDER,
    ]
    assert "not installed" in result.issues[-3].message
    assert "Duplicate Source identity" in result.issues[-2].message
    assert "bad weights" in result.issues[-1].message
