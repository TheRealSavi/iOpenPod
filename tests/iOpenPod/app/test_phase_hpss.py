"""The optimized filter must preserve the established separation exactly."""

from typing import TYPE_CHECKING, Literal, cast

import librosa
import numpy as np
import pytest
from numpy.typing import NDArray
from tests.iOpenPod.app.test_phase_audio import pulse_audio

from iOpenPod.app import phase_audio
from iOpenPod.app.phase_hpss import separate_magnitude

if TYPE_CHECKING:
    from collections.abc import Callable

type _Spectrum = NDArray[np.float32]


def reference(magnitude: _Spectrum) -> tuple[_Spectrum, _Spectrum]:
    hpss = cast(
        "Callable[..., tuple[_Spectrum, _Spectrum]]",
        librosa.decompose.hpss,
    )
    return hpss(magnitude, kernel_size=31, margin=(2.0, 2.0))


@pytest.mark.parametrize("shape", [(1, 1), (5, 7), (17, 23), (1025, 65)])
@pytest.mark.parametrize("order", ["C", "F"])
@pytest.mark.parametrize("kind", ["noise", "zeros", "ties"])
def test_median_boundaries_masks_and_layout_match_the_reference(
    shape: tuple[int, int], order: Literal["C", "F"], kind: str
) -> None:
    values = np.random.default_rng(97).random(shape, dtype=np.float32)
    if kind == "zeros":
        values.fill(0)
    elif kind == "ties":
        values = np.round(values * 3)
    magnitude = np.array(values, order=order)
    magnitude.flags.writeable = False
    for actual, expected in zip(
        separate_magnitude(magnitude), reference(magnitude), strict=True
    ):
        assert np.array_equal(actual, expected)
        assert actual.dtype == expected.dtype
        assert actual.flags.f_contiguous == expected.flags.f_contiguous
        assert actual.flags.c_contiguous == expected.flags.c_contiguous


def test_complete_chart_matches_the_previous_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm, _ = pulse_audio()
    actual = phase_audio.analyze_phase_pcm(pcm, length_ms=30_000)
    monkeypatch.setattr(phase_audio, "separate_magnitude", reference)
    expected = phase_audio.analyze_phase_pcm(pcm, length_ms=30_000)
    assert actual == expected
