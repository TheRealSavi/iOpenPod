"""Fixed Phase HPSS policy using contiguous two-dimensional median filters."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

type _Spectrum = NDArray[np.float32]


def separate_magnitude(magnitude: _Spectrum) -> tuple[_Spectrum, _Spectrum]:
    """Preserve the 31-bin, margin-2, power-2 real-magnitude HPSS mapping.

    SciPy's specialized filter uses zero padding. Symmetric padding followed by
    cropping reproduces ndimage's half-sample ``reflect`` boundary, including
    short final blocks. Filtering rows in both orientations improves locality.
    """
    median = cast(
        "Callable[..., _Spectrum]",
        import_module("scipy.signal").medfilt2d,
    )
    softmask = cast(
        "Callable[..., _Spectrum]",
        import_module("librosa.util").softmask,
    )

    def filtered_rows(values: _Spectrum) -> _Spectrum:
        padded = np.pad(values, ((0, 0), (15, 15)), mode="symmetric")
        return median(padded, kernel_size=(1, 31))[:, 15:-15]

    # Preserve the STFT's array order as librosa does. Changing layout can change
    # floating-point reduction order in the downstream evidence measurements.
    harmonic = np.empty_like(magnitude)
    harmonic[:] = filtered_rows(magnitude)
    percussive = np.empty_like(magnitude)
    percussive[:] = filtered_rows(magnitude.T).T
    harmonic_mask = softmask(harmonic, percussive * 2.0, power=2.0, split_zeros=False)
    percussive_mask = softmask(percussive, harmonic * 2.0, power=2.0, split_zeros=False)
    return magnitude * harmonic_mask, magnitude * percussive_mask
