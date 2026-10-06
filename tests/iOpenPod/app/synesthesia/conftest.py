from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from iOpenPod.app.synesthesia import (
    AnalysisMode,
    AnalysisRequest,
    DecodedAudio,
    DeterministicMusicAnalyzer,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from iOpenPod.app.synesthesia import TrackAnalysis


@pytest.fixture(scope="session")
def synthetic_audio() -> DecodedAudio:
    sample_rate = 16_000
    duration = 18.0
    times: NDArray[np.float32] = np.arange(
        round(sample_rate * duration), dtype=np.float32
    ) / np.float32(sample_rate)
    samples: NDArray[np.float32] = np.zeros_like(times)
    first: NDArray[np.bool_] = np.less(times, 6.0)
    second: NDArray[np.bool_] = np.logical_and(
        np.greater_equal(times, 6.0), np.less(times, 12.0)
    )
    third: NDArray[np.bool_] = np.greater_equal(times, 12.0)
    samples[first] = 0.05 * np.sin(2.0 * np.pi * 80.0 * times[first])
    samples[second] = (
        0.22 * np.sin(2.0 * np.pi * 220.0 * times[second])
        + 0.16 * np.sin(2.0 * np.pi * 330.0 * times[second])
        + 0.12 * np.sin(2.0 * np.pi * 440.0 * times[second])
    )
    random = np.random.default_rng(42)
    samples[third] = 0.12 * np.sin(
        2.0 * np.pi * 4_000.0 * times[third]
    ) + 0.08 * random.normal(size=int(np.sum(third)))
    for beat, seconds in enumerate(np.arange(6.0, 12.0, 0.5)):
        index = round(seconds * sample_rate)
        strength = 0.72 if beat % 4 == 0 else 0.38
        samples[index : index + 320] += np.hanning(320).astype(np.float32) * strength
    for beat, seconds in enumerate(np.arange(12.0, 18.0, 0.25)):
        index = round(seconds * sample_rate)
        strength = 0.46 if beat % 4 == 0 else 0.25
        samples[index : index + 100] += np.hanning(100).astype(np.float32) * strength
    stereo = np.column_stack((samples, np.roll(samples, 20) * 0.8))
    return DecodedAudio(
        sample_rate,
        np.ascontiguousarray(stereo, dtype=np.float32),
    )


@pytest.fixture(scope="session")
def synthetic_analysis(synthetic_audio: DecodedAudio) -> TrackAnalysis:
    return DeterministicMusicAnalyzer().analyze(
        synthetic_audio,
        AnalysisRequest(title="Synthetic", mode=AnalysisMode.STANDARD),
        title="Synthetic",
        checkpoint=lambda: None,
        progress=lambda _progress: None,
    )
