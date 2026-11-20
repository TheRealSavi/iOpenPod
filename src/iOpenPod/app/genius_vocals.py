"""Bounded vocal evidence using the optional, already installed instrument model."""

from __future__ import annotations

import logging
from threading import Lock
from typing import TYPE_CHECKING, Protocol

import numpy as np

from iOpenPod.app.genius_audio import GeniusVocalAnalysisError, GeniusVocalEvidence
from iOpenPod.app.phase_parts import HOP, RATE, PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.phase_parts import PhasePart


class GeniusVocalAnalyzer(Protocol):
    @property
    def identity(self) -> str: ...

    def analyze(
        self, pcm: bytes, *, checkpoint: Callable[[], None]
    ) -> GeniusVocalEvidence: ...

    def close(self) -> None: ...


def _sample(pcm: bytes) -> tuple[bytes, tuple[tuple[int, int], ...]]:
    """At most six eight-second windows spread over the entire recording."""
    count = len(pcm) // 4
    if count <= 48 * RATE:
        return pcm, ((0, count),)
    width = 8 * RATE
    starts = np.linspace(0, count - width, 6, dtype=np.int64)
    chunks = [pcm[int(start) * 4 : (int(start) + width) * 4] for start in starts]
    return b"".join(chunks), tuple(
        (index * width, (index + 1) * width) for index in range(6)
    )


def vocal_fraction(
    parts: tuple[PhasePart, ...], intervals: tuple[tuple[int, int], ...]
) -> float:
    """Estimate occupied one-second windows; don't count tiny vocal-stem leakage."""
    vocals = next((part for part in parts if part.kind is PhasePartKind.VOCALS), None)
    if vocals is None or len({part.kind for part in parts}) != 6:
        raise ValueError("Vocal analysis requires all six source measurements")
    count = vocals.energy.size
    if any(part.energy.size != count for part in parts):
        raise ValueError("Vocal source measurements must share one time grid")
    total = np.sum(np.stack([part.energy**2 for part in parts]), axis=0)
    vocal = vocals.energy**2
    active = occupied = 0
    floor = float(np.max(total)) * 1e-4
    for first, last in intervals:
        # Ignore the edges of each disjoint sample: artificial joins are not music.
        begin = round((first + RATE) / HOP)
        end = min(count, round((last - RATE) / HOP))
        step = round(RATE / HOP)
        for position in range(begin, end, step):
            stop = min(end, position + step)
            if stop - position < step // 2:
                continue
            power = float(np.mean(total[position:stop]))
            if power <= floor or power <= 0:
                continue
            active += 1
            occupied += float(np.mean(vocal[position:stop])) / power >= 0.1
    if not active:
        raise ValueError("Vocal analysis did not find enough audible music")
    return occupied / active


class ManagedGeniusVocals:
    """Serialize inference and retain one optional worker for one preparation."""

    def __init__(self, sources: ManagedPhaseSources) -> None:
        self._sources = sources
        # The managed worker replaces its live identity after the first request.
        # Cache against the installed receipt captured before starting it, so a
        # new preparation can recognize the same model/runtime without inference.
        self._identity = f"genius-vocals-v1:{sources.identity}"
        self._lock = Lock()

    @property
    def identity(self) -> str:
        return self._identity

    def analyze(
        self, pcm: bytes, *, checkpoint: Callable[[], None]
    ) -> GeniusVocalEvidence:
        samples, intervals = _sample(pcm)
        while not self._lock.acquire(timeout=0.05):
            checkpoint()
        try:
            checkpoint()
            parts = self._sources.analyze(
                samples, sample_rate=RATE, channels=1, checkpoint=checkpoint
            )
            checkpoint()
            try:
                fraction = vocal_fraction(parts, intervals)
            except ValueError as error:
                raise GeniusVocalAnalysisError(str(error)) from error
            return GeniusVocalEvidence(
                self.identity, fraction, len(samples) / (4 * RATE)
            )
        finally:
            self._lock.release()

    def close(self) -> None:
        self._sources.close()


def installed_genius_vocals() -> GeniusVocalAnalyzer | None:
    try:
        installed = ManagedPhaseSources.installed()
    except (OSError, ValueError):
        logging.getLogger(__name__).warning(
            "Optional instrument analysis is unavailable", exc_info=True
        )
        return None
    if installed is None:
        return None
    # Do not trigger a model download as a side effect of Library save or Sync.
    checkpoint = (
        installed.directory.parent / "models/hub/checkpoints/5c90dfd2-34c22ccb.th"
    )
    if not checkpoint.is_file():
        return None
    return ManagedGeniusVocals(installed.for_analysis())
