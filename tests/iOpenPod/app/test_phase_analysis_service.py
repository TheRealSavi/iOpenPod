"""Exercise the real FFmpeg-to-librosa path on an authored audio file."""

import wave
from pathlib import Path

import numpy as np
import pytest
from tests.iOpenPod.app.test_phase_audio import pulse_audio

from iOpenPod.app.phase_analysis import PhaseAnalysisService
from storage import HostPath, Storage
from storage.media_processing import find_media_tool
from storage.testing import VirtualStoragePlatform


def test_real_decoder_generates_native_chart_envelope(tmp_path: Path) -> None:
    if find_media_tool("ffmpeg") is None:
        pytest.skip("FFmpeg is unavailable")
    pcm, _ = pulse_audio()
    source = tmp_path / "pulse.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22_050)
        output.writeframes(
            (np.frombuffer(pcm, dtype="<f4") * 32767).astype("<i2").tobytes()
        )
    root = tmp_path / "device"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as session:
        data = PhaseAnalysisService().analyze(
            HostPath(source),
            input_suffix=".wav",
            length_ms=30_000,
            session=session,
            checkpoint=lambda: None,
        )
    assert data[:10] == b"pha\x02\x01\0\0\0\x40\0"
    assert len(data) > 300
