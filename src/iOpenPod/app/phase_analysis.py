"""Decode and analyze one verified Phase source using the shared audio runner."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait
from copy import copy
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING

from iOpenPod.app.genius_analysis import (
    FFmpegGeniusPCMDecoder,
    GeniusAudioDecodeError,
    GeniusPCMDecoder,
)
from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from iOpenPod.app.phase_audio import (
    PHASE_ANALYSIS_VERSION,
    analyze_phase_pcm,
    finish_phase_analysis,
    measure_phase_mix,
)
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_sources import (
    DemucsPhaseSources,
    PhaseOverlapSources,
    PhaseSourceAnalyzer,
)
from iPodDB.games import build_phase_analysis
from storage.media_processing import available_compute_threads

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import DevicePath, FilesystemSession, HostPath
    from storage.media_processing import MediaToolFinder

    from .phase_parts import PhasePart


_OVERLAP_PCM_LIMIT = 256 * 1024 * 1024


class _MixStoppedError(Exception):
    pass


class PhaseAnalysisService:
    def __init__(
        self,
        decoder: GeniusPCMDecoder | None = None,
        *,
        source_analyzer: PhaseSourceAnalyzer | None = None,
        use_sources: bool = True,
        find_tool: MediaToolFinder | None = None,
    ) -> None:
        self._automatic_sources = source_analyzer is None and use_sources
        self._activity = PhaseActivity(PhaseStage.DECODING)
        self._custom_decoder = decoder is not None
        self._find_tool = find_tool
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
    def activity(self) -> PhaseActivity:
        if self._activity.stage is PhaseStage.SOURCES and isinstance(
            self._sources, (DemucsPhaseSources, ManagedPhaseSources)
        ):
            return replace(
                self._sources.activity, parallel_mix=self._activity.parallel_mix
            )
        return self._activity

    @property
    def identity(self) -> str:
        provider = "acoustic"
        if self._sources is not None:
            try:
                provider = self._sources.identity
            except Exception:
                self._fallback()
        return f"{PHASE_ANALYSIS_VERSION}:{provider}:{'stereo' if self._stereo else 'mono'}"

    def _fallback(self) -> None:
        logging.getLogger(__name__).warning(
            "Phase instrument analysis failed; using acoustic analysis for this run",
            exc_info=True,
        )
        self.close()
        self._sources = None

    def close(self) -> None:
        """Release an optional worker when this preparation ends."""
        if isinstance(self._sources, ManagedPhaseSources):
            self._sources.close()

    def for_analysis(self) -> PhaseAnalysisService:
        """Retry tool discovery on the next save, sharing it across this run."""
        updated = copy(self)
        updated._activity = PhaseActivity(PhaseStage.DECODING)
        if self._automatic_sources:
            try:
                updated._sources = ManagedPhaseSources.installed()
                if updated._sources is not None:
                    updated._sources = updated._sources.for_analysis()
            except Exception:
                logging.getLogger(__name__).warning(
                    "Installed Phase runtime is unavailable",
                    exc_info=True,
                )
                updated._sources = None
            if updated._sources is None and DemucsPhaseSources.available():
                updated._sources = DemucsPhaseSources()
        if (
            isinstance(self._sources, (DemucsPhaseSources, ManagedPhaseSources))
            and not self._automatic_sources
        ):
            updated._sources = self._sources.for_analysis()
        if not self._custom_decoder:
            updated._stereo = updated._sources is not None
            updated._decoder = FFmpegGeniusPCMDecoder(
                find_tool=self._find_tool,
                maximum_duration_seconds=1801,
                sample_rate_hz=44_100 if updated._stereo else 22_050,
                channels=2 if updated._stereo else 1,
            )
        elif isinstance(self._decoder, FFmpegGeniusPCMDecoder):
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
        self._activity = PhaseActivity(PhaseStage.DECODING)
        checkpoint()
        try:
            pcm = self._decoder.decode(
                source,
                input_suffix=input_suffix,
                session=session,
                checkpoint=checkpoint,
            )
        except GeniusAudioDecodeError as error:
            raise ValueError(f"Phase audio could not be decoded: {error}") from error
        import numpy as np

        rate, channels = (44_100, 2) if self._stereo else (22_050, 1)
        if (
            len(pcm) % (4 * channels)
            or len(pcm) > 1801 * rate * channels * 4
            or not 30 <= length_ms // 1000 <= 1800
        ):
            raise ValueError("Invalid Phase PCM frame size")
        samples = np.frombuffer(pcm, dtype="<f4").reshape(-1, channels)
        if abs(len(samples) / rate - length_ms / 1000) > 3:
            raise ValueError("Decoded Phase audio disagrees with the Track")
        for first in range(0, len(samples), rate * 10):
            checkpoint()
            if not np.isfinite(samples[first : first + rate * 10]).all():
                raise ValueError("Decoded Phase audio disagrees with the Track")
        del samples
        pcm = pcm[: round(length_ms * rate / 1000) * channels * 4]
        if self._overlap_supported(pcm):
            return self._analyze_overlapped(
                pcm,
                rate=rate,
                channels=channels,
                length_ms=length_ms,
                checkpoint=checkpoint,
            )
        parts = self._measure_parts(
            pcm, rate=rate, channels=channels, checkpoint=checkpoint
        )
        self._activity = PhaseActivity(PhaseStage.ACOUSTIC)
        checkpoint()
        pcm = self._mono_pcm(pcm, rate=rate)
        chart = analyze_phase_pcm(
            pcm, length_ms=length_ms, checkpoint=checkpoint, parts=parts
        )
        self._activity = PhaseActivity(PhaseStage.ENCODING)
        checkpoint()
        return build_phase_analysis(chart)

    def _overlap_supported(self, pcm: bytes) -> bool:
        # Bound the extra lifetime of stereo PCM and avoid competing on tiny CPUs.
        # Capability is a scheduling hint; source failures still follow fallback.
        try:
            return (
                len(pcm) <= _OVERLAP_PCM_LIMIT
                and available_compute_threads() >= 4
                and isinstance(self._sources, PhaseOverlapSources)
                and self._sources.supports_mix_overlap is True
            )
        except Exception:
            return False

    def _mono_pcm(self, pcm: bytes, *, rate: int) -> bytes:
        if not self._stereo:
            return pcm
        import librosa
        import numpy as np

        mono = np.frombuffer(pcm, dtype="<f4").reshape(-1, 2).mean(axis=1)
        return (
            librosa.resample(mono, orig_sr=rate, target_sr=22_050)
            .astype("<f4")
            .tobytes()
        )

    def _analyze_overlapped(
        self,
        pcm: bytes,
        *,
        rate: int,
        channels: int,
        length_ms: int,
        checkpoint: Callable[[], None],
    ) -> bytes:
        # Complete conversion before GPU work starts to limit transient buffers.
        mono = self._mono_pcm(pcm, rate=rate)
        stopped = Event()

        def worker_checkpoint() -> None:
            if stopped.is_set():
                raise _MixStoppedError("Phase whole-mix measurement stopped")

        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="phase-mix"
        ) as worker:
            measured = worker.submit(
                measure_phase_mix,
                mono,
                length_ms=length_ms,
                checkpoint=worker_checkpoint,
            )

            def checked() -> None:
                checkpoint()
                # A DSP failure is mandatory-analysis failure, never an optional
                # source failure. _measure_parts preserves checkpoint exceptions.
                if measured.done():
                    measured.result()

            try:
                self._activity = PhaseActivity(PhaseStage.SOURCES, parallel_mix=True)
                parts = self._measure_parts(
                    pcm, rate=rate, channels=channels, checkpoint=checked
                )
                self._activity = PhaseActivity(PhaseStage.ACOUSTIC)
                while not measured.done():
                    checked()
                    wait((measured,), timeout=0.05)
                checked()
                evidence = measured.result()
            finally:
                stopped.set()
        self._activity = PhaseActivity(PhaseStage.COMBINING)
        checkpoint()
        chart = finish_phase_analysis(evidence, parts=parts, checkpoint=checkpoint)
        self._activity = PhaseActivity(PhaseStage.ENCODING)
        checkpoint()
        return build_phase_analysis(chart)

    def _measure_parts(
        self,
        pcm: bytes,
        *,
        rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        parts: tuple[PhasePart, ...] = ()
        if self._sources is not None:
            self._activity = replace(self._activity, stage=PhaseStage.SOURCES)
            interruption: Exception | None = None

            def source_checkpoint() -> None:
                nonlocal interruption
                try:
                    checkpoint()
                except Exception as error:
                    interruption = error
                    raise

            try:
                parts = self._sources.analyze(
                    pcm,
                    sample_rate=rate,
                    channels=channels,
                    checkpoint=source_checkpoint,
                )
                if not parts:
                    raise ValueError("Phase source analysis returned no parts")
            except Exception:
                if interruption is not None:
                    raise interruption from None
                checkpoint()
                self._fallback()
        else:
            logging.getLogger(__name__).info(
                "Phase uses acoustic analysis; optional instrument separation is unavailable or disabled"
            )
        return parts
