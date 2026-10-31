"""Exercise the real FFmpeg-to-librosa path on an authored audio file."""

import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from tests.iOpenPod.app.test_phase_audio import pulse_audio

from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_parts import PhasePart, PhasePartKind, measure_part
from storage import HostPath, Storage
from storage.media_processing import find_media_tool
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("with_sources", [False, True])
def test_real_decoder_generates_native_chart_envelope(
    tmp_path: Path, with_sources: bool
) -> None:
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
        provider = _KnownSource() if with_sources else None
        service = PhaseAnalysisService(use_sources=False, source_analyzer=provider)
        data = service.analyze(
            HostPath(source),
            input_suffix=".wav",
            length_ms=30_000,
            session=session,
            checkpoint=lambda: None,
        )
    assert data[:10] == b"pha\x02\x01\0\0\0\x40\0"
    assert len(data) > 300
    if provider is not None:
        assert provider.formats == [(44_100, 2)]
        assert "known-source" in service.identity
        assert "stereo" in service.identity


class _KnownSource:
    identity = "known-source"

    def __init__(self) -> None:
        self.formats: list[tuple[int, int]] = []

    def analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        import librosa

        checkpoint()
        self.formats.append((sample_rate, channels))
        mono = np.frombuffer(pcm, dtype="<f4").reshape(-1, channels).mean(axis=1)
        mono = librosa.resample(mono, orig_sr=sample_rate, target_sr=22_050)
        bands, energy, chroma = measure_part(mono.astype(np.float32))
        return (PhasePart(PhasePartKind.GUITAR, bands, energy, chroma),)
