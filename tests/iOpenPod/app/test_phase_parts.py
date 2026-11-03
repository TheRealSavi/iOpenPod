"""Source features retain their previous exact arithmetic and amplitude scale."""

from typing import Literal, cast

import librosa
import numpy as np
import pytest
from numpy.typing import NDArray

from iOpenPod.app.phase_parts import (
    FFT,
    HOP,
    PHASE_BANDS_HZ,
    RATE,
    measure_band_attacks,
    measure_part,
)


def reference_attacks(
    magnitude: NDArray[np.float32] | NDArray[np.float64],
) -> NDArray[np.float64]:
    frequencies = np.fft.rfftfreq(FFT, 1 / RATE)
    increase = np.maximum(np.diff(magnitude, axis=1, prepend=magnitude[:, :1]), 0)
    return np.asarray(
        [
            np.sqrt(
                np.sum(
                    increase[(frequencies >= low) & (frequencies <= high)] ** 2,
                    axis=0,
                )
            )
            / FFT
            for low, high in PHASE_BANDS_HZ
        ],
        dtype=np.float64,
    )


@pytest.mark.parametrize("frames", [1, 5, 65, 517])
@pytest.mark.parametrize("order", ["C", "F", "strided"])
@pytest.mark.parametrize("kind", ["noise", "zeros", "ties"])
@pytest.mark.parametrize("wide", [False, True])
def test_attack_measurement_preserves_reference_arithmetic(
    frames: int, order: Literal["C", "F", "strided"], kind: str, wide: bool
) -> None:
    values: NDArray[np.float32] | NDArray[np.float64] = np.random.default_rng(
        87
    ).random((FFT // 2 + 1, frames))
    if not wide:
        values = values.astype(np.float32)
    if kind == "zeros":
        values.fill(0)
    elif kind == "ties":
        values = np.round(values * 3)
    magnitude = np.array(
        values,
        dtype=np.float64 if wide else np.float32,
        order="F" if order == "F" else "C",
    )
    if order == "strided":
        magnitude = np.repeat(magnitude, 2, axis=1)[:, ::2]
    magnitude.flags.writeable = False
    typed_magnitude = cast("NDArray[np.float32] | NDArray[np.float64]", magnitude)
    actual = measure_band_attacks(typed_magnitude)
    expected = reference_attacks(typed_magnitude)
    assert actual.dtype == expected.dtype
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("kind", ["noise", "silence", "tones"])
def test_source_pitch_classes_preserve_original_pooling(kind: str) -> None:
    samples = np.random.default_rng(41).normal(0, 0.05, RATE * 2).astype(np.float32)
    if kind == "silence":
        samples.fill(0)
    elif kind == "tones":
        t = np.arange(samples.size) / RATE
        signal = np.zeros(samples.size)
        for hz, gain in ((110, 0.2), (440, 0.1), (523.25, 0.04)):
            signal += np.sin(2 * np.pi * hz * t) * gain
        samples = signal.astype(np.float32)
    samples.flags.writeable = False
    magnitude = np.abs(librosa.stft(samples, n_fft=FFT, hop_length=HOP))
    power = magnitude**2
    frequencies = np.fft.rfftfreq(FFT, 1 / RATE)
    valid = (frequencies >= 65) & (frequencies <= 4000)
    classes = np.round(69 + 12 * np.log2(frequencies[valid] / 440)).astype(int) % 12
    expected = np.zeros((12, power.shape[1]), dtype=np.float64)
    for pitch in range(12):
        expected[pitch] = np.sum(power[valid][classes == pitch], axis=0)
    expected /= np.maximum(np.linalg.norm(expected, axis=0), 1e-12)
    _, _, actual, attacks = measure_part(samples)
    assert np.array_equal(actual, expected)
    assert np.array_equal(attacks, reference_attacks(magnitude))
