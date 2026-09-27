"""Qt Multimedia adapter for the Application Layer playback seam."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.playback._qt_logging import quiet_qt_ffmpeg_initialization
from iOpenPod.app.playback.backend import (
    PlaybackAttemptId,
    PlaybackFailure,
    PlaybackSourceError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.playback.backend import PlaybackSource, PlaybackSourceProvider
    from iPodDB.library import Track


class _QtPlaybackIODevice(QIODevice):
    """Expose range-readable Track bytes as a seekable Qt device."""

    sourceFailed = Signal(object)

    def __init__(
        self,
        source: PlaybackSource,
        parent: QObject | None = None,
    ) -> None:
        if parent is None:
            super().__init__()
        else:
            super().__init__(parent)
        self._source = source

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self._source.byte_count

    def readData(self, max_length: int) -> bytes:
        remaining = self.size() - self.pos()
        if max_length <= 0 or remaining <= 0:
            return b""
        try:
            return self._source.read_at(
                self.pos(),
                min(max_length, remaining),
            )
        except Exception as error:
            self.setErrorString(str(error))
            self.sourceFailed.emit(error)
            return b""

    def writeData(
        self,
        _data: bytes | bytearray | memoryview[int],
        _length: int,
    ) -> int:
        return -1


class _QtPlaybackEventRelay(QObject):
    """Tag one Qt player's events with their immutable playback attempt."""

    playingChanged = Signal(int, bool)
    positionChanged = Signal(int, int)
    finished = Signal(int)
    failed = Signal(object)

    def __init__(
        self,
        attempt_id: PlaybackAttemptId,
        track_id: int,
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._attempt_id = attempt_id
        self._track_id = track_id
        self._failure_reported = False

    @Slot(object)
    def playback_state_changed(self, state: object) -> None:
        self.playingChanged.emit(
            self._attempt_id,
            state == QMediaPlayer.PlaybackState.PlayingState,
        )

    @Slot(int)
    def position_changed(self, position_ms: int) -> None:
        self.positionChanged.emit(self._attempt_id, position_ms)

    @Slot(object)
    def media_status_changed(self, status: object) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit(self._attempt_id)

    @Slot(object, str)
    def error_occurred(self, error: object, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        error_name = (
            error.name
            if isinstance(error, QMediaPlayer.Error)
            else type(error).__name__
        )
        self.report_failure(
            RuntimeError(
                message or source_text("The selected Track could not be played.")
            ),
            error_type=str(error_name),
        )

    @Slot(object)
    def source_failed(self, error: object) -> None:
        resolved = error if isinstance(error, Exception) else OSError(str(error))
        self.report_failure(resolved)

    def report_failure(
        self,
        error: Exception,
        *,
        error_type: str | None = None,
    ) -> None:
        if self._failure_reported:
            return
        self._failure_reported = True
        self.playingChanged.emit(self._attempt_id, False)
        self.failed.emit(
            PlaybackFailure(
                attempt_id=self._attempt_id,
                track_id=self._track_id,
                message=exception_text(error)
                or source_text("The selected Track could not be played."),
                error_type=error_type or type(error).__name__,
            )
        )


class QtPlaybackBackend(QObject):
    """Play one Track at a time through QMediaPlayer and QAudioOutput."""

    playingChanged = Signal(int, bool)
    positionChanged = Signal(int, int)
    finished = Signal(int)
    failed = Signal(object)

    def __init__(
        self,
        source_provider: PlaybackSourceProvider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_provider = source_provider
        with quiet_qt_ffmpeg_initialization():
            self._audio_output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._source_device: _QtPlaybackIODevice | None = None
        self._event_relay: _QtPlaybackEventRelay | None = None
        self._closed = False

    def subscribe_playing_changed(
        self,
        callback: Callable[[PlaybackAttemptId, bool], None],
    ) -> None:
        self.playingChanged.connect(callback)

    def subscribe_position_changed(
        self,
        callback: Callable[[PlaybackAttemptId, int], None],
    ) -> None:
        self.positionChanged.connect(callback)

    def subscribe_finished(
        self,
        callback: Callable[[PlaybackAttemptId], None],
    ) -> None:
        self.finished.connect(callback)

    def subscribe_failed(
        self,
        callback: Callable[[PlaybackFailure], None],
    ) -> None:
        self.failed.connect(callback)

    def start(self, attempt_id: PlaybackAttemptId, track: Track) -> None:
        if self._closed:
            return
        self._discard_source()
        relay = _QtPlaybackEventRelay(attempt_id, track.track_id, self)
        relay.playingChanged.connect(self.playingChanged.emit)
        relay.positionChanged.connect(self.positionChanged.emit)
        relay.finished.connect(self.finished.emit)
        relay.failed.connect(self.failed.emit)
        self._event_relay = relay
        try:
            source = self._source_provider.open_playback_source(track)
            device = _QtPlaybackIODevice(source, self)
            if not device.open(QIODevice.OpenModeFlag.ReadOnly):
                raise OSError(
                    device.errorString() or source_text("Could not open playback data")
                )
            self._player.playbackStateChanged.connect(relay.playback_state_changed)
            self._player.positionChanged.connect(relay.position_changed)
            self._player.mediaStatusChanged.connect(relay.media_status_changed)
            self._player.errorOccurred.connect(relay.error_occurred)
            device.sourceFailed.connect(relay.source_failed)
            self._source_device = device
            self._player.setSourceDevice(
                device,
                QUrl.fromLocalFile(source.file_name),
            )
            self._player.play()
        except (OSError, PlaybackSourceError) as error:
            relay.report_failure(error)

    def play(self) -> None:
        if not self._closed:
            self._player.play()

    def pause(self) -> None:
        if not self._closed:
            self._player.pause()

    def stop(self) -> None:
        if self._closed:
            return
        self._discard_source()

    def seek(self, position_ms: int) -> None:
        if not self._closed:
            self._player.setPosition(max(0, position_ms))

    def set_volume(self, percent: int) -> None:
        bounded = min(100, max(0, percent))
        self._audio_output.setVolume(bounded / 100.0)

    def close(self) -> None:
        if self._closed:
            return
        self._discard_source()
        self._closed = True

    def _discard_source(self) -> None:
        self._player.stop()
        # Qt documents that a null source ceases all I/O for the previous media.
        # Only then can the custom stream be closed without racing the decoder.
        self._player.setSource(QUrl())
        device = self._source_device
        self._source_device = None
        if device is not None:
            device.close()
            device.deleteLater()
        relay = self._event_relay
        self._event_relay = None
        if relay is not None:
            relay.deleteLater()


__all__ = ["QtPlaybackBackend"]
