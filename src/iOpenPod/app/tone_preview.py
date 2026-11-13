"""Bounded approximate Host preview of the native monophonic note sequence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

if TYPE_CHECKING:
    from iPodDB.alarms import AlarmToneNote


def tone_pcm(notes: tuple[AlarmToneNote, ...], sample_rate: int = 44100) -> bytes:
    """Quiet sine preview; native speaker timbre is hardware-dependent."""
    if (
        not notes
        or len(notes) > 1000
        or not 1 <= sum(note.duration_ms for note in notes) <= 30000
    ):
        raise ValueError("Preview is available for tones up to 30 seconds.")
    chunks: list[bytes] = []
    for note in notes:
        if not 0 <= note.frequency <= 65535 or not 1 <= note.duration_ms <= 65535:
            raise ValueError("This tone contains an unsupported note.")
        count = round(note.duration_ms * sample_rate / 1000)
        # Above Nyquist cannot be faithfully represented by this Host preview.
        wave = (
            np.sin(np.arange(count) * (2 * np.pi * note.frequency / sample_rate))
            if 0 < note.frequency < sample_rate / 2
            else np.zeros(count)
        )
        fade = min(round(sample_rate * 0.004), count // 2)
        if fade:
            wave[:fade] *= np.linspace(0, 1, fade)
            wave[-fade:] *= np.linspace(1, 0, fade)
        chunks.append((wave * 6500).astype("<i2").tobytes())
    return b"".join(chunks)


class TonePreview(QObject):
    changed = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sink: QAudioSink | None = None
        self._buffer: QBuffer | None = None

    @property
    def playing(self) -> bool:
        return self._sink is not None

    def play(self, notes: tuple[AlarmToneNote, ...]) -> None:
        self.stop()
        try:
            payload = tone_pcm(notes)
            format = QAudioFormat()
            format.setSampleRate(44100)
            format.setChannelCount(1)
            format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            device = QMediaDevices.defaultAudioOutput()
            if device.isNull() or not device.isFormatSupported(format):
                raise ValueError("No audio output is available for tone preview.")
            self._buffer = QBuffer(self)
            self._buffer.setData(QByteArray(payload))
            self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self._sink = QAudioSink(device, format, self)
            self._sink.stateChanged.connect(self._state_changed)
            self._sink.start(self._buffer)
            self.changed.emit()
        except ValueError as error:
            self.stop()
            self.failed.emit(str(error))

    def stop(self) -> None:
        sink, self._sink = self._sink, None
        if sink is not None:
            sink.reset()
            sink.deleteLater()
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None
        self.changed.emit()

    def _state_changed(self, state: QAudio.State) -> None:
        if self._sink is None:
            return
        if state.value == QAudio.State.IdleState.value:
            QTimer.singleShot(0, self.stop)
        elif (
            state.value == QAudio.State.StoppedState.value
            and self._sink.error().value != QAudio.Error.NoError.value
        ):
            self.failed.emit("The audio output could not play this preview.")
            QTimer.singleShot(0, self.stop)
