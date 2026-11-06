"""Qt Multimedia adapter for the Application Layer playback seam."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QIODevice, QLocale, QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioOutput,
    QMediaMetaData,
    QMediaPlayer,
    QVideoFrame,
    QVideoSink,
)

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.playback._qt_io import QtPlaybackIODevice
from iOpenPod.app.playback._qt_logging import quiet_qt_ffmpeg_initialization
from iOpenPod.app.playback.backend import (
    PlaybackAttemptId,
    PlaybackFailure,
    PlaybackSourceError,
)
from iOpenPod.app.playback.video_output import PlaybackSubtitleTrack

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iPodDB.library import Track


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
    subtitlesChanged = Signal()

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
        # Keep the current frame available before a viewer is opened, including
        # while paused. Qt does not repaint a newly attached sink when paused.
        self._video_sink = QVideoSink(self)
        self._player.setVideoSink(self._video_sink)
        self._source_device: QtPlaybackIODevice | None = None
        self._event_relay: _QtPlaybackEventRelay | None = None
        self._closed = False
        self._pending_subtitle_track: int | None = None
        self._player.tracksChanged.connect(self.subtitlesChanged.emit)
        self._player.activeTracksChanged.connect(self.subtitlesChanged.emit)
        self._player.positionChanged.connect(self._apply_pending_subtitle)

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
            device = QtPlaybackIODevice(source, self)
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

    def set_video_output(self, output: QObject | None) -> None:
        """Present the existing player's video without replacing its source."""

        if not self._closed:
            previous_sink = self._current_video_sink()
            frame = (
                previous_sink.videoFrame()
                if previous_sink is not None
                else QVideoFrame()
            )
            subtitle = previous_sink.subtitleText() if previous_sink is not None else ""
            if output is None:
                self._player.setVideoSink(self._video_sink)
            else:
                self._player.setVideoOutput(output)
            sink = self._player.videoSink()
            if sink is not previous_sink:
                sink.setVideoFrame(frame)
                sink.setSubtitleText(subtitle)
                if previous_sink is not None:
                    previous_sink.setVideoFrame(QVideoFrame())
                    previous_sink.setSubtitleText("")

    @property
    def subtitle_tracks(self) -> tuple[PlaybackSubtitleTrack, ...]:
        if self._closed or self._source_device is None:
            return ()
        return tuple(
            _subtitle_track(index, metadata)
            for index, metadata in enumerate(self._player.subtitleTracks())
        )

    @property
    def active_subtitle_track(self) -> int:
        if self._closed or self._source_device is None:
            return -1
        if self._pending_subtitle_track is not None:
            return self._pending_subtitle_track
        return self._player.activeSubtitleTrack()

    def subscribe_subtitles_changed(self, callback: Callable[[], None]) -> None:
        self.subtitlesChanged.connect(callback)

    def set_subtitle_track(self, index: int) -> None:
        if self._closed or self._source_device is None:
            return
        if not -1 <= index < len(self.subtitle_tracks):
            return
        if index == self.active_subtitle_track:
            return
        had_pending_choice = self._pending_subtitle_track is not None
        self._pending_subtitle_track = None
        if index >= 0 and self._player.position() == 0:
            # Qt FFmpeg can report EndOfMedia when changing streams before its
            # clock starts. Retain the intent until the first position advance.
            self._pending_subtitle_track = index
            self.subtitlesChanged.emit()
            return
        self._player.setActiveSubtitleTrack(index)
        if had_pending_choice:
            self.subtitlesChanged.emit()
        if index == -1:
            sink = self._current_video_sink()
            if sink is not None:
                sink.setSubtitleText("")

    @Slot(int)
    def _apply_pending_subtitle(self, _position_ms: int) -> None:
        index = self._pending_subtitle_track
        if index is not None and self._player.position() > 0:
            self._pending_subtitle_track = None
            self.set_subtitle_track(index)

    def close(self) -> None:
        if self._closed:
            return
        self._discard_source()
        self.set_video_output(None)
        self._closed = True

    def _discard_source(self) -> None:
        self._pending_subtitle_track = None
        self._player.stop()
        # Qt documents that a null source ceases all I/O for the previous media.
        # Only then can the custom stream be closed without racing the decoder.
        self._player.setSource(QUrl())
        sink = self._current_video_sink()
        if sink is not None:
            sink.setVideoFrame(QVideoFrame())
            sink.setSubtitleText("")
        self._video_sink.setVideoFrame(QVideoFrame())
        self._video_sink.setSubtitleText("")
        device = self._source_device
        self._source_device = None
        if device is not None:
            device.close()
            device.deleteLater()
        relay = self._event_relay
        self._event_relay = None
        if relay is not None:
            relay.deleteLater()
        self.subtitlesChanged.emit()

    def _current_video_sink(self) -> QVideoSink | None:
        # Qt clears this pointer when its surface is destroyed. The shipped
        # non-null return annotation omits that valid lifecycle state.
        return self._player.videoSink()


def _subtitle_track(index: int, metadata: QMediaMetaData) -> PlaybackSubtitleTrack:
    language: object = metadata.value(QMediaMetaData.Key.Language)
    return PlaybackSubtitleTrack(
        index,
        metadata.stringValue(QMediaMetaData.Key.Title).strip(),
        QLocale.languageToString(language)
        if isinstance(language, QLocale.Language)
        and language not in (QLocale.Language.AnyLanguage, QLocale.Language.C)
        else "",
    )


__all__ = ["QtPlaybackBackend"]
