"""Internal array calibration and public-signal construction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from .models import FloatSeries, ScalarSignal, SignalValidity, TimeGrid, VectorSignal

if TYPE_CHECKING:
    from collections.abc import Sequence

FloatArray = NDArray[np.float32]


def as_float(values: object) -> FloatArray:
    return np.asarray(values, dtype=np.float32)


def align(values: object, frame_count: int) -> FloatArray:
    source = as_float(values)
    if source.shape[-1] == frame_count:
        return source
    if source.shape[-1] == 1:
        return np.repeat(source, frame_count, axis=-1)
    old = np.linspace(0.0, 1.0, source.shape[-1], dtype=np.float32)
    new = np.linspace(0.0, 1.0, frame_count, dtype=np.float32)
    flat = source.reshape(-1, source.shape[-1])
    result = np.stack([np.interp(new, old, row) for row in flat])
    return result.reshape(*source.shape[:-1], frame_count).astype(np.float32)


def pad(values: object, length: int) -> FloatArray:
    source = as_float(values)
    if len(source) >= length:
        return source[:length]
    padding = (
        (0, length - len(source)),
        *((0, 0) for _ in range(source.ndim - 1)),
    )
    return np.pad(source, padding, mode="edge").astype(np.float32)


def smooth(values: object, radius: int) -> FloatArray:
    source = as_float(values)
    if radius <= 1 or len(source) < 3:
        return source.copy()
    radius = min(radius, max(1, len(source) // 3))
    padded = np.pad(source.astype(np.float64), (radius, radius), mode="edge")
    cumulative = np.concatenate(([0.0], np.cumsum(padded)))
    width = radius * 2 + 1
    return ((cumulative[width:] - cumulative[:-width]) / width).astype(np.float32)


def robust_unit(
    values: object, *, lower: float = 8.0, upper: float = 97.0
) -> FloatArray:
    source = as_float(values)
    low = float(np.percentile(source, lower))
    high = float(np.percentile(source, upper))
    if high - low < 1e-6:
        return np.zeros_like(source)
    result: FloatArray = np.clip((source - low) / (high - low), 0.0, 1.0).astype(
        np.float32
    )
    return result


def dbfs_unit(
    values: object, *, floor: float = -78.0, ceiling: float = -36.0
) -> FloatArray:
    result: FloatArray = np.clip(
        (as_float(values) - floor) / (ceiling - floor), 0.0, 1.0
    ).astype(np.float32)
    return result


def positive_distribution(values: object) -> FloatArray:
    source = np.maximum(as_float(values), 0.0)
    totals = np.sum(source, axis=1, keepdims=True)
    result = source / np.maximum(totals, 1e-12)
    empty = totals[:, 0] <= 1e-12
    result[empty] = 1.0 / source.shape[1]
    return result.astype(np.float32)


def cosine_change(values: object, lag: int) -> FloatArray:
    source = as_float(values)
    lag = max(1, lag)
    prior = np.roll(source, lag, axis=0)
    prior[:lag] = source[:lag]
    similarity = np.sum(source * prior, axis=1) / (
        np.linalg.norm(source, axis=1) * np.linalg.norm(prior, axis=1) + 1e-8
    )
    result: FloatArray = np.clip(1.0 - similarity, 0.0, 1.0).astype(np.float32)
    return result


def scalar_signal(
    grid: TimeGrid,
    values: object,
    *,
    confidence: object | float = 1.0,
    unit: str,
    validity: SignalValidity = SignalValidity.VALID,
    circular: bool = False,
) -> ScalarSignal:
    data = as_float(values).reshape(-1)
    reliability = _confidence(confidence, grid.frame_count)
    return ScalarSignal(
        grid,
        FloatSeries.from_values(data),
        FloatSeries.from_values(reliability),
        unit,
        validity,
        circular,
    )


def vector_signal(
    grid: TimeGrid,
    values: object,
    components: Sequence[str],
    *,
    confidence: object | float = 1.0,
    unit: str,
    validity: SignalValidity = SignalValidity.VALID,
    distribution: bool = False,
) -> VectorSignal:
    data = as_float(values)
    if data.ndim != 2 or data.shape[0] != grid.frame_count:
        raise ValueError("Vector source does not match its analysis grid")
    reliability = _confidence(confidence, grid.frame_count)
    return VectorSignal(
        grid,
        FloatSeries.from_values(data.reshape(-1)),
        FloatSeries.from_values(reliability),
        tuple(components),
        unit,
        validity,
        distribution,
    )


def frame_crest_db(
    samples: FloatArray, frame_size: int, hop_size: int, frame_count: int
) -> FloatArray:
    import librosa

    if samples.ndim == 1:
        frames = librosa.util.frame(
            samples, frame_length=frame_size, hop_length=hop_size
        ).T
        peak = np.max(np.abs(frames), axis=1)
        rms = np.sqrt(np.mean(frames * frames, axis=1)) + 1e-8
    else:
        left = librosa.util.frame(
            samples[:, 0], frame_length=frame_size, hop_length=hop_size
        ).T
        right = librosa.util.frame(
            samples[:, 1], frame_length=frame_size, hop_length=hop_size
        ).T
        peak = np.maximum(np.max(np.abs(left), axis=1), np.max(np.abs(right), axis=1))
        rms = (
            np.sqrt(
                0.5 * (np.mean(left * left, axis=1) + np.mean(right * right, axis=1))
            )
            + 1e-8
        )
    return pad(20.0 * np.log10(peak / rms + 1e-8), frame_count)


def calibrated_band_levels_dbfs(
    power: FloatArray,
    frequencies: FloatArray,
    frame_size: int,
    edges_hz: Sequence[float],
) -> FloatArray:
    """Measure one-sided FFT energy against digital full scale."""

    weights = np.ones(len(frequencies), dtype=np.float64)
    if len(weights) > 2:
        weights[1:-1] = 2.0
    window = np.hanning(frame_size).astype(np.float64)
    normalizer = frame_size * float(np.sum(window * window))
    columns: list[FloatArray] = []
    for low, high in zip(edges_hz, (*edges_hz[1:], math.inf), strict=True):
        mask: NDArray[np.bool_] = np.logical_and(
            np.greater_equal(frequencies, low), np.less(frequencies, high)
        )
        if not np.any(mask):
            mean_square = np.zeros(power.shape[1], dtype=np.float64)
        else:
            weighted = power[mask].astype(np.float64) * weights[mask, None]
            mean_square = np.sum(weighted, axis=0) / normalizer
        columns.append(
            (10.0 * np.log10(np.maximum(mean_square, 1e-12))).astype(np.float32)
        )
    return np.column_stack(columns).astype(np.float32)


def _confidence(value: object | float, frame_count: int) -> FloatArray:
    if isinstance(value, int | float):
        return np.full(frame_count, float(value), dtype=np.float32)
    result = as_float(value).reshape(-1)
    if len(result) != frame_count:
        raise ValueError("Signal confidence does not match its analysis grid")
    return np.clip(result, 0.0, 1.0).astype(np.float32)


__all__ = [
    "FloatArray",
    "align",
    "as_float",
    "calibrated_band_levels_dbfs",
    "cosine_change",
    "dbfs_unit",
    "frame_crest_db",
    "pad",
    "positive_distribution",
    "robust_unit",
    "scalar_signal",
    "smooth",
    "vector_signal",
]
