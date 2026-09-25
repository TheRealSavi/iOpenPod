from __future__ import annotations

import shutil
import wave
from typing import TYPE_CHECKING

import numpy as np
import pytest

from iOpenPod.app.synesthesia import (
    AnalysisMode,
    AnalysisProgress,
    AnalysisRequest,
    AnalysisStage,
    FFmpegDecoder,
    WholeTrackMusicAnalyzer,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_ffmpeg_decoder_reads_one_audio_stream_into_bounded_stereo(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tone.wav"
    sample_rate = 8_000
    times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    tone = np.asarray(
        np.sin(2.0 * np.pi * 440.0 * times) * np.iinfo(np.int16).max * 0.2,
        dtype="<i2",
    )
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(tone.tobytes())
    progress: list[AnalysisProgress] = []

    decoded = FFmpegDecoder(
        sample_rate_hz=16_000,
        maximum_duration_seconds=2.0,
    ).decode(
        source,
        checkpoint=lambda: None,
        progress=progress.append,
    )

    assert decoded.samples.shape == (16_000, 2)
    assert decoded.samples.dtype == np.float32
    assert decoded.samples.flags.c_contiguous
    assert np.allclose(decoded.samples[:, 0], decoded.samples[:, 1])
    assert progress[0].stage is AnalysisStage.DECODE
    assert progress[-1].stage is AnalysisStage.DECODE

    analysis = WholeTrackMusicAnalyzer(
        decoder=FFmpegDecoder(
            sample_rate_hz=16_000,
            maximum_duration_seconds=2.0,
        ),
        enrichers=(),
    ).analyze(
        source,
        AnalysisRequest(mode=AnalysisMode.STANDARD),
    )

    assert analysis.metadata.title == "tone"
    assert analysis.metadata.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert analysis.timeline.spectrum.band_levels_dbfs.components == (
        "sub-bass",
        "bass",
        "low-mid",
        "mid",
        "upper-mid",
        "presence",
        "brilliance",
    )
