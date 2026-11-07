"""Compact, time-aligned evidence for identifiable Phase musical parts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

RATE = 22_050
HOP = 256
FFT = 2048
PHASE_BANDS_HZ = ((80, 300), (400, 1500), (2000, 4500))

_FREQUENCIES = np.fft.rfftfreq(FFT, 1 / RATE)
_ATTACK_MASKS: tuple[NDArray[np.bool_], ...] = tuple(
    np.greater_equal(_FREQUENCIES, low) & np.less_equal(_FREQUENCIES, high)
    for low, high in PHASE_BANDS_HZ
)
_CHROMA_VALID: NDArray[np.bool_] = (_FREQUENCIES >= 65) & (_FREQUENCIES <= 4000)
_CHROMA_CLASSES = (
    np.round(69 + 12 * np.log2(_FREQUENCIES[_CHROMA_VALID] / 440)).astype(int) % 12
)
_CHROMA_MASKS: tuple[NDArray[np.bool_], ...] = tuple(
    np.equal(_CHROMA_CLASSES, pitch) for pitch in range(12)
)
_FREQUENCIES.flags.writeable = False
_CHROMA_CLASSES.flags.writeable = False
for _lookup in (*_ATTACK_MASKS, _CHROMA_VALID, *_CHROMA_MASKS):
    _lookup.flags.writeable = False


@lru_cache(maxsize=1)
def _mel_band_masks() -> tuple[NDArray[np.bool_], ...]:
    import librosa

    edges = librosa.mel_frequencies(n_mels=64, fmin=20, fmax=RATE / 2)
    masks = (edges < 250, (edges >= 250) & (edges < 2000), edges >= 2000)
    for mask in masks:
        mask.flags.writeable = False
    return masks


def measure_band_attacks(magnitude: NDArray[np.floating[Any]]) -> NDArray[np.float64]:
    """Linear spectral increases in the shipped subbands, on one amplitude scale.

    Detection uses log-mel novelty separately. Neither the original producer's
    filter nor its quantizer is recovered; this is our measurement policy.
    """
    values: list[NDArray[np.floating[Any]]] = []
    for mask in _ATTACK_MASKS:
        band = magnitude[mask]
        increase = np.maximum(np.diff(band, axis=1, prepend=band[:, :1]), 0)
        values.append(np.sqrt(np.sum(increase**2, axis=0)) / FFT)
    return np.asarray(values, dtype=np.float64)


class PhasePartKind(StrEnum):
    DRUMS = "drums"
    BASS = "bass"
    OTHER = "other"
    VOCALS = "vocals"
    PIANO = "piano"
    GUITAR = "guitar"


@dataclass(frozen=True, slots=True)
class PhasePart:
    """Detection novelty (`bands`) and linear attack `magnitudes` stay distinct."""

    kind: PhasePartKind
    bands: NDArray[np.float64]
    energy: NDArray[np.float64]
    chroma: NDArray[np.float64]
    magnitudes: NDArray[np.float64]

    def __post_init__(self) -> None:
        count = self.energy.size
        if (
            count == 0
            or self.energy.shape != (count,)
            or self.bands.shape != (3, count)
            or self.chroma.shape != (12, count)
            or self.magnitudes.shape != (3, count)
            or any(
                not np.isfinite(a).all() or np.any(a < 0)
                for a in (self.bands, self.energy, self.chroma, self.magnitudes)
            )
        ):
            raise ValueError("Invalid Phase source evidence")
        for array in (self.bands, self.energy, self.chroma, self.magnitudes):
            array.flags.writeable = False


def measure_part(
    samples: NDArray[np.float32],
) -> tuple[
    NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]
]:
    """Measure one bounded separated waveform, at the common Phase frame grid."""
    import librosa

    api: Any = librosa
    # Float32 PCM produces a complex64 STFT and float32 magnitudes. Narrow the
    # dynamic librosa boundary before NumPy overloads propagate unknown types.
    magnitude = cast(
        "NDArray[np.float32]", np.abs(api.stft(samples, n_fft=FFT, hop_length=HOP))
    )
    power = magnitude**2
    energy = np.sqrt(np.mean(power, axis=0)) / FFT
    mel = api.feature.melspectrogram(S=power, sr=RATE, n_fft=FFT, n_mels=64, fmin=20)
    log_mel = api.power_to_db(mel, ref=1.0, top_db=80.0)
    masks = _mel_band_masks()
    bands = np.asarray(
        [
            api.onset.onset_strength(
                S=log_mel[mask],
                sr=RATE,
                n_fft=FFT,
                hop_length=HOP,
                center=False,
                max_size=3,
            )
            for mask in masks
        ],
        dtype=np.float64,
    )
    previous = np.pad(magnitude[:, :-4], ((0, 0), (4, 0)))
    norm, old_norm = np.linalg.norm(magnitude, axis=0), np.linalg.norm(previous, axis=0)
    similarity = np.sum(magnitude * previous, axis=0) / np.maximum(
        norm * old_norm, 1e-12
    )
    bands[:, ~((1 - similarity > 0.02) | (norm > old_norm * 1.08))] = 0
    # Direct FFT-to-pitch-class pooling avoids per-block tuning estimation and
    # keeps recurring phrase descriptors consistent across separation blocks.
    valid_power = power[_CHROMA_VALID]
    chroma = np.zeros((12, power.shape[1]), dtype=np.float64)
    for pitch, mask in enumerate(_CHROMA_MASKS):
        chroma[pitch] = np.sum(valid_power[mask], axis=0)
    del valid_power
    chroma /= np.maximum(np.linalg.norm(chroma, axis=0), 1e-12)
    return bands, energy.astype(np.float64), chroma, measure_band_attacks(magnitude)
