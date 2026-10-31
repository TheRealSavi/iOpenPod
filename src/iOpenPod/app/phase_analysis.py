"""Decode and analyze one verified Phase source using the shared audio runner."""

from __future__ import annotations

import logging
from copy import copy
from typing import TYPE_CHECKING

from iOpenPod.app.genius_analysis import (
    FFmpegGeniusPCMDecoder,
    GeniusAudioDecodeError,
    GeniusPCMDecoder,
)
from iOpenPod.app.phase_audio import PHASE_ANALYSIS_VERSION, analyze_phase_pcm
from iOpenPod.app.phase_sources import DemucsPhaseSources, PhaseSourceAnalyzer
from iPodDB.games import build_phase_analysis

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import DevicePath, FilesystemSession, HostPath
    from storage.media_processing import MediaToolFinder

    from .phase_parts import PhasePart


class PhaseAnalysisService:
    def __init__(
        self,
        decoder: GeniusPCMDecoder | None = None,
        *,
        source_analyzer: PhaseSourceAnalyzer | None = None,
        use_sources: bool = True,
        find_tool: MediaToolFinder | None = None,
    ) -> None:
        self._sources = source_analyzer
        if self._sources is None and use_sources and DemucsPhaseSources.available():
            self._sources = DemucsPhaseSources()
        self._stereo = decoder is None and self._sources is not None
        self._decoder = decoder or FFmpegGeniusPCMDecoder(
            find_tool=find_tool,
            maximum_duration_seconds=1801,
            sample_rate_hz=44_100 if self._stereo else 22_050,
            channels=2 if self._stereo else 1,
        )

    @property
    def identity(self) -> str:
        provider = self._sources.identity if self._sources else "acoustic"
        return f"{PHASE_ANALYSIS_VERSION}:{provider}:{'stereo' if self._stereo else 'mono'}"

    def for_analysis(self) -> PhaseAnalysisService:
        """Retry tool discovery on the next save, sharing it across this run."""
        updated = copy(self)
        if isinstance(self._decoder, FFmpegGeniusPCMDecoder):
            updated._decoder = self._decoder.for_analysis()
        return updated

    def analyze(
        self,
        source: DevicePath | HostPath,
        *,
        input_suffix: str,
        length_ms: int,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        try:
            pcm = self._decoder.decode(
                source,
                input_suffix=input_suffix,
                session=session,
                checkpoint=checkpoint,
            )
        except GeniusAudioDecodeError as error:
            raise ValueError(f"Phase audio could not be decoded: {error}") from error
        import librosa
        import numpy as np

        rate, channels = (44_100, 2) if self._stereo else (22_050, 1)
        if (
            len(pcm) % (4 * channels)
            or len(pcm) > 1801 * rate * channels * 4
            or not 30 <= length_ms // 1000 <= 1800
        ):
            raise ValueError("Invalid Phase PCM frame size")
        samples = np.frombuffer(pcm, dtype="<f4").reshape(-1, channels)
        if (
            not np.isfinite(samples).all()
            or abs(len(samples) / rate - length_ms / 1000) > 3
        ):
            raise ValueError("Decoded Phase audio disagrees with the Track")
        del samples
        pcm = pcm[: round(length_ms * rate / 1000) * channels * 4]
        parts: tuple[PhasePart, ...] = ()
        if self._sources is not None:
            # Failure must not cache acoustic output under an instrument identity.
            parts = self._sources.analyze(
                pcm, sample_rate=rate, channels=channels, checkpoint=checkpoint
            )
            if not parts:
                raise ValueError("Phase source analysis returned no parts")
        else:
            logging.getLogger(__name__).info(
                "Phase uses acoustic analysis; optional instrument separation is unavailable or disabled"
            )
        if self._stereo:
            mono = np.frombuffer(pcm, dtype="<f4").reshape(-1, 2).mean(axis=1)
            pcm = (
                librosa.resample(mono, orig_sr=rate, target_sr=22_050)
                .astype("<f4")
                .tobytes()
            )
        chart = analyze_phase_pcm(
            pcm, length_ms=length_ms, checkpoint=checkpoint, parts=parts
        )
        return build_phase_analysis(chart)
