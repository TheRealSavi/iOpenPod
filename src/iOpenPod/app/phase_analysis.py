"""Decode and analyze one verified Phase source using the shared audio runner."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from iOpenPod.app.genius_analysis import (
    FFmpegGeniusPCMDecoder,
    GeniusAudioDecodeError,
    GeniusPCMDecoder,
)
from iOpenPod.app.phase_audio import analyze_phase_pcm
from iPodDB.games import build_phase_analysis

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import DevicePath, FilesystemSession, HostPath


class PhaseAnalysisService:
    def __init__(self, decoder: GeniusPCMDecoder | None = None) -> None:
        self._decoder = decoder or FFmpegGeniusPCMDecoder(maximum_duration_seconds=1801)

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
        chart = analyze_phase_pcm(pcm, length_ms=length_ms, checkpoint=checkpoint)
        return build_phase_analysis(chart)
