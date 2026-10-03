"""Exercise the packaged decoder without a device or an audio endpoint."""

import io
import wave
from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, QIODevice, QTimer, QUrl
from PySide6.QtMultimedia import QAudioBuffer, QAudioBufferOutput, QMediaPlayer

from iOpenPod.app.playback._qt_io import QtPlaybackIODevice


@dataclass(frozen=True, slots=True)
class _CheckSource:
    data: bytes
    file_name: str = "runtime-check.wav"

    @property
    def byte_count(self) -> int:
        return len(self.data)

    def read_at(self, offset: int, length: int) -> bytes:
        return self.data[offset : offset + length]


def check_playback_runtime() -> None:
    """Require decoded PCM from Qt's FFmpeg backend, without playing sound."""
    encoded = io.BytesIO()
    with wave.open(encoded, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(b"\x00\x00" * 800)

    player = QMediaPlayer()
    if not player.isAvailable():
        raise RuntimeError("Qt Multimedia playback backend is unavailable")
    check_source = _CheckSource(encoded.getvalue())
    source = QtPlaybackIODevice(check_source)
    output = QAudioBufferOutput()
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    decoded_frames = 0
    errors: list[str] = []

    def decoded(buffer: QAudioBuffer) -> None:
        nonlocal decoded_frames
        decoded_frames += buffer.frameCount()
        if decoded_frames:
            loop.quit()

    def failed(error: QMediaPlayer.Error, message: str) -> None:
        errors.append(f"{error.name}: {message}")
        loop.quit()

    output.audioBufferReceived.connect(decoded)
    player.errorOccurred.connect(failed)
    # Buffer output requires FFmpeg. A native fallback may report an available
    # player yet reject ALAC Tracks; constructing QMediaPlayer cannot catch that.
    # Omitting QAudioOutput keeps this usable on CI without speakers or sound.
    player.setAudioBufferOutput(output)
    try:
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError("Could not open the playback runtime check source")
        player.setSourceDevice(source, QUrl.fromLocalFile(check_source.file_name))
        timer.start(5_000)
        player.play()
        if not decoded_frames and not errors:
            loop.exec()
        if errors:
            raise RuntimeError(
                "Qt Multimedia playback check failed: " + "; ".join(errors)
            )
        if not decoded_frames:
            raise RuntimeError("Qt Multimedia FFmpeg backend did not decode audio")
    finally:
        timer.stop()
        player.stop()
        player.setSource(QUrl())
        source.close()
