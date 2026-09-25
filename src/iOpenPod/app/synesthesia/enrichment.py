"""Optional learned enrichment for instrument-aware Source analysis."""

from __future__ import annotations

import importlib
import importlib.util
import math
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Protocol, cast

import librosa
import numpy as np

from ._signals import FloatArray, align, dbfs_unit, scalar_signal, smooth
from .models import (
    AnalysisProgress,
    AnalysisStage,
    EventKind,
    MusicalEvent,
    Provenance,
    SourceAnalysis,
    SourceKind,
    TimeGrid,
    TrackAnalysis,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .audio import DecodedAudio


class _ArrayReduction(Protocol):
    def __call__(
        self,
        values: FloatArray,
        *,
        axis: int | None = None,
    ) -> FloatArray | np.float32: ...


class _DecibelTransform(Protocol):
    def __call__(
        self,
        values: FloatArray,
        *,
        ref: _ArrayReduction,
    ) -> FloatArray: ...


class _OnsetStrength(Protocol):
    def __call__(
        self,
        *,
        S: FloatArray,  # noqa: N803 - librosa's public keyword is uppercase.
        sr: float,
        hop_length: int,
        center: bool = True,
    ) -> FloatArray: ...


def _library_member(namespace: object, name: str) -> object:
    return getattr(namespace, name)


_ARRAY_MAX = cast("_ArrayReduction", np.max)
_AMPLITUDE_TO_DB = cast(
    "_DecibelTransform", _library_member(librosa, "amplitude_to_db")
)
_ONSET_STRENGTH = cast(
    "_OnsetStrength", _library_member(librosa.onset, "onset_strength")
)


@dataclass(frozen=True, slots=True)
class AnalysisEnrichment:
    """Typed additions from one independent analysis provider."""

    sources: tuple[SourceAnalysis, ...] = ()
    events: tuple[MusicalEvent, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    replace_sources: bool = False


class AnalysisEnricher(Protocol):
    """Optional provider that may enrich, but never gate, core analysis."""

    @property
    def provider_name(self) -> str: ...

    def available(self) -> bool: ...

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment: ...


@dataclass(frozen=True, slots=True)
class _StemMeasurements:
    rms: FloatArray
    loudness_dbfs: FloatArray
    onset: FloatArray
    centroid_hz: FloatArray
    pan: FloatArray
    width: FloatArray


class DemucsSourceEnricher:
    """Separate vocals, drums, bass, and other with optional HTDemucs."""

    provider_name = "HTDemucs"

    def __init__(
        self,
        *,
        device: str | None = None,
        shifts: int = 1,
        overlap: float = 0.25,
    ) -> None:
        if shifts < 1:
            raise ValueError("Demucs shifts must be positive")
        if not 0.0 <= overlap < 1.0:
            raise ValueError("Demucs overlap must be in [0, 1)")
        self._device = device
        self._shifts = shifts
        self._overlap = overlap

    def available(self) -> bool:
        return all(
            importlib.util.find_spec(module) is not None
            for module in ("demucs", "torch")
        )

    def enrich(
        self,
        audio: DecodedAudio,
        analysis: TrackAnalysis,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> AnalysisEnrichment:
        if not self.available():
            raise RuntimeError("HTDemucs and PyTorch are not installed")
        checkpoint()
        progress(
            AnalysisProgress(
                0.86,
                AnalysisStage.SOURCES,
                "Separating vocals, drums, bass, and other with HTDemucs",
            )
        )
        torch_api: Any = importlib.import_module("torch")
        demucs_api: Any = importlib.import_module("demucs.api")
        separator = demucs_api.Separator(
            model="htdemucs",
            device=self._device or _default_device(torch_api),
            shifts=self._shifts,
            overlap=self._overlap,
            split=True,
            jobs=0,
            progress=False,
        )
        waveform = torch_api.from_numpy(audio.samples.T.copy())
        origin_tensor, stem_tensors = separator.separate_tensor(
            waveform, sr=audio.sample_rate_hz
        )
        checkpoint()
        origin = _tensor_numpy(origin_tensor)
        raw_stems = {
            name: _tensor_numpy(tensor)
            for name, tensor in cast("dict[str, Any]", stem_tensors).items()
        }
        expected = ("vocals", "drums", "bass", "other")
        if any(name not in raw_stems for name in expected):
            raise RuntimeError("HTDemucs did not return its four expected sources")
        reconstruction = sum(
            (raw_stems[name] for name in expected), np.zeros_like(origin)
        )
        residual = float(
            np.linalg.norm(origin - reconstruction) / (np.linalg.norm(origin) + 1e-8)
        )
        separation_confidence = float(np.clip(math.exp(-2.5 * residual), 0.2, 0.98))
        provenance = Provenance(
            "HTDemucs",
            _package_version("demucs"),
            "htdemucs hybrid waveform-spectrogram source separation",
        )
        grid = analysis.timeline.grid
        frame_size = max(
            512,
            round(analysis.timeline.window_seconds * audio.sample_rate_hz),
        )
        hop_size = max(1, round(grid.step_seconds * audio.sample_rate_hz))
        stems = tuple(
            (
                name,
                SourceKind(name),
                np.ascontiguousarray(raw_stems[name].T, dtype=np.float32),
            )
            for name in expected
        )
        measured = tuple(
            _measure_stem(
                samples,
                sample_rate=audio.sample_rate_hz,
                frame_size=frame_size,
                hop_size=hop_size,
                frame_count=grid.frame_count,
            )
            for _, _, samples in stems
        )
        total_power = (
            sum(
                (item.rms * item.rms for item in measured),
                np.zeros(grid.frame_count, dtype=np.float32),
            )
            + 1e-8
        )
        sources: list[SourceAnalysis] = []
        events: list[MusicalEvent] = []
        for (source_id, kind, _), item in zip(stems, measured, strict=True):
            presence = np.clip(item.rms * item.rms / total_power, 0.0, 1.0).astype(
                np.float32
            )
            audible = dbfs_unit(item.loudness_dbfs, floor=-78.0, ceiling=-42.0)
            confidence = np.clip(
                separation_confidence * (0.55 + 0.45 * audible), 0.0, 0.98
            ).astype(np.float32)
            sources.append(
                SourceAnalysis(
                    source_id,
                    kind,
                    source_id.title(),
                    float(np.mean(confidence)),
                    scalar_signal(
                        grid, presence, confidence=confidence, unit="power share"
                    ),
                    scalar_signal(
                        grid,
                        item.loudness_dbfs,
                        confidence=confidence,
                        unit="dBFS",
                    ),
                    scalar_signal(
                        grid, item.onset, confidence=confidence, unit="normalized"
                    ),
                    scalar_signal(
                        grid, item.centroid_hz, confidence=confidence, unit="Hz"
                    ),
                    scalar_signal(grid, item.pan, confidence=confidence, unit="signed"),
                    scalar_signal(
                        grid, item.width, confidence=confidence, unit="normalized"
                    ),
                    provenance,
                )
            )
            events.extend(
                _activity_events(
                    source_id,
                    smooth(presence * audible, max(1, round(0.25 / grid.step_seconds))),
                    grid,
                    analysis.metadata.duration_seconds,
                    separation_confidence,
                )
            )
        return AnalysisEnrichment(
            tuple(sources),
            tuple(sorted(events, key=lambda event: (event.seconds, event.event_id))),
            (provenance,),
            replace_sources=True,
        )


def _measure_stem(
    samples: FloatArray,
    *,
    sample_rate: int,
    frame_size: int,
    hop_size: int,
    frame_count: int,
) -> _StemMeasurements:
    if len(samples) < frame_size:
        samples = np.pad(samples, ((0, frame_size - len(samples)), (0, 0)))
    left_spectrum = librosa.stft(
        samples[:, 0],
        n_fft=frame_size,
        hop_length=hop_size,
        window="hann",
        center=False,
    )
    right_spectrum = librosa.stft(
        samples[:, 1],
        n_fft=frame_size,
        hop_length=hop_size,
        window="hann",
        center=False,
    )
    magnitude = np.sqrt(
        0.5
        * (
            np.abs(left_spectrum).astype(np.float32) ** 2
            + np.abs(right_spectrum).astype(np.float32) ** 2
        )
    ).astype(np.float32)
    del left_spectrum, right_spectrum
    left_frames = librosa.util.frame(
        samples[:, 0], frame_length=frame_size, hop_length=hop_size
    ).T
    right_frames = librosa.util.frame(
        samples[:, 1], frame_length=frame_size, hop_length=hop_size
    ).T
    rms = align(
        np.sqrt(
            0.5
            * (
                np.mean(left_frames * left_frames, axis=1)
                + np.mean(right_frames * right_frames, axis=1)
            )
        ),
        frame_count,
    )
    loudness_dbfs = (20.0 * np.log10(np.maximum(rms, 1e-7))).astype(np.float32)
    onset_raw = align(
        _ONSET_STRENGTH(
            S=_AMPLITUDE_TO_DB(magnitude, ref=_ARRAY_MAX),
            sr=sample_rate,
            hop_length=hop_size,
            center=False,
        ),
        frame_count,
    )
    onset = (1.0 - np.exp(-np.maximum(onset_raw, 0.0) / 1.5)).astype(np.float32)
    centroid_hz = align(
        librosa.feature.spectral_centroid(S=magnitude, sr=sample_rate)[0], frame_count
    )
    left = librosa.util.frame(
        samples[:, 0], frame_length=frame_size, hop_length=hop_size
    ).T
    right = librosa.util.frame(
        samples[:, 1], frame_length=frame_size, hop_length=hop_size
    ).T
    left_energy = np.mean(left * left, axis=1) + 1e-10
    right_energy = np.mean(right * right, axis=1) + 1e-10
    pan = align(
        (right_energy - left_energy) / (right_energy + left_energy), frame_count
    )
    side = np.mean((left - right) ** 2, axis=1)
    middle = np.mean((left + right) ** 2, axis=1) + 1e-10
    width = np.clip(align(np.sqrt(side / middle), frame_count) / 2.0, 0.0, 1.0)
    return _StemMeasurements(
        rms.astype(np.float32),
        loudness_dbfs,
        onset,
        centroid_hz.astype(np.float32),
        np.clip(pan, -1.0, 1.0).astype(np.float32),
        width.astype(np.float32),
    )


def _activity_events(
    source_id: str,
    activity: FloatArray,
    grid: TimeGrid,
    duration_seconds: float,
    confidence: float,
) -> tuple[MusicalEvent, ...]:
    active = activity >= 0.12
    transitions = np.diff(active.astype(np.int8), prepend=np.int8(0))
    events: list[MusicalEvent] = []
    for index in np.flatnonzero(transitions):
        seconds = min(duration_seconds, grid.time_at(int(index)))
        entering = transitions[index] > 0
        events.append(
            MusicalEvent(
                f"{source_id}-{'entrance' if entering else 'exit'}-{int(index)}",
                EventKind.SOURCE_ENTRANCE if entering else EventKind.SOURCE_EXIT,
                seconds,
                float(np.clip(activity[index], 0.0, 1.0)),
                confidence,
                source_id=source_id,
            )
        )
    return tuple(events)


def _tensor_numpy(tensor: Any) -> FloatArray:
    return np.asarray(tensor.detach().cpu().float().numpy(), dtype=np.float32)


def _default_device(torch_api: Any) -> str:
    return "cuda" if bool(torch_api.cuda.is_available()) else "cpu"


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


__all__ = ["AnalysisEnricher", "AnalysisEnrichment", "DemucsSourceEnricher"]
