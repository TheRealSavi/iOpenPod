"""Synchronize PlaybackController state with an optional Host media session."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage
from iOpenPod.app.playback.system_media.session import (
    NullSystemMediaSession,
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandKind,
    SystemMediaSession,
    SystemMediaSnapshot,
)
from iOpenPod.app.playback_controller import PlaybackController

_TIMELINE_PUBLISH_INTERVAL_MS = 5_000
_NOW_PLAYING_ARTWORK_TARGET_PX = 512

logger = logging.getLogger(__name__)


class SystemMediaBridge(QObject):
    """Route controller snapshots and Host transport intents without a backend."""

    _commandReceived = Signal(object)

    def __init__(
        self,
        controller: PlaybackController,
        session: SystemMediaSession,
        parent: QObject | None = None,
        *,
        artwork_controller: ArtworkController | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._session = session
        self._artwork_controller = artwork_controller
        self._artwork: SystemMediaArtwork | None = None
        self._last_published: SystemMediaSnapshot | None = None
        self._has_published = False
        self._closed = False
        self._timeline_timer = QTimer(self)
        self._timeline_timer.setSingleShot(True)
        self._timeline_timer.setInterval(_TIMELINE_PUBLISH_INTERVAL_MS)
        self._timeline_timer.timeout.connect(self._publish)
        self._commandReceived.connect(
            self._dispatch_command,
            Qt.ConnectionType.QueuedConnection,
        )
        controller.currentTrackChanged.connect(self._current_track_changed)
        controller.playingChanged.connect(self._publish_immediately)
        controller.positionChanged.connect(self._position_changed)
        controller.seeked.connect(self._seeked)
        controller.volumeChanged.connect(self._publish_immediately)
        if artwork_controller is not None:
            artwork_controller.artworkReady.connect(self._artwork_ready)
            artwork_controller.generationChanged.connect(
                self._artwork_generation_changed
            )
        try:
            session.set_command_handler(self._queue_command)
        except Exception:
            self._disable_session("initialize")
        self._publish(force=True)
        self._request_current_artwork()

    def close(self) -> None:
        """Clear Host state and release native command handlers exactly once."""

        if self._closed:
            return
        self._closed = True
        self._timeline_timer.stop()
        self._try_close_operation(
            "detach commands from",
            lambda: self._session.set_command_handler(None),
        )
        self._try_close_operation("clear", lambda: self._session.publish(None))
        self._try_close_operation("close", self._session.close)

    def _try_close_operation(
        self,
        operation: str,
        callback: Callable[[], None],
    ) -> None:
        try:
            callback()
        except Exception:
            logger.warning(
                "Could not %s the Host system-media session",
                operation,
                exc_info=True,
            )

    def _queue_command(self, command: SystemMediaCommand) -> None:
        if not self._closed:
            self._commandReceived.emit(command)

    @Slot(object)
    def _dispatch_command(self, value: object) -> None:
        if self._closed or not isinstance(value, SystemMediaCommand):
            return
        kind = value.kind
        if kind is SystemMediaCommandKind.PLAY:
            self._controller.play()
        elif kind is SystemMediaCommandKind.PAUSE:
            self._controller.pause()
        elif kind is SystemMediaCommandKind.TOGGLE_PLAY_PAUSE:
            self._controller.toggle_play_pause()
        elif kind is SystemMediaCommandKind.NEXT:
            self._controller.next()
        elif kind is SystemMediaCommandKind.PREVIOUS:
            self._controller.previous()
        elif kind is SystemMediaCommandKind.SEEK and value.position_ms is not None:
            self._controller.seek(value.position_ms)
        elif (
            kind is SystemMediaCommandKind.SET_VOLUME
            and value.volume_percent is not None
        ):
            self._controller.set_volume(value.volume_percent)

    @Slot(int)
    def _seeked(self, position_ms: int) -> None:
        self._publish_immediately()
        try:
            self._session.seeked(position_ms)
        except Exception:
            self._disable_session("publish a seek")

    @Slot(object)
    def _current_track_changed(self, _value: object) -> None:
        self._artwork = None
        self._publish_immediately()
        self._request_current_artwork()

    @Slot(object)
    def _artwork_ready(self, value: object) -> None:
        track = self._controller.current_track
        if (
            self._closed
            or not isinstance(value, ArtworkImage)
            or track is None
            or value.artwork_id != track.artwork_id
        ):
            return
        retained = self._artwork
        if (
            retained is not None
            and retained.artwork_id == value.artwork_id
            and _artwork_resolution(value.width, value.height)
            < _artwork_resolution(retained.width, retained.height)
        ):
            # ArtworkController serves every GUI and Host request. A small card
            # decode may therefore finish after the Now Playing decode; never let
            # that shared signal downgrade the cover already published to the Host.
            return
        self._artwork = SystemMediaArtwork(
            cache_key=value.cache_key,
            artwork_id=value.artwork_id,
            width=value.width,
            height=value.height,
            rgb888=value.rgb888,
        )
        self._publish_immediately()

    @Slot(int)
    def _artwork_generation_changed(self, _generation: int) -> None:
        self._artwork = None
        self._publish_immediately()

    def _request_current_artwork(self) -> None:
        artwork_controller = self._artwork_controller
        track = self._controller.current_track
        if (
            self._closed
            or artwork_controller is None
            or track is None
            or track.artwork_id <= 0
        ):
            return
        image = artwork_controller.request(
            track.artwork_id,
            _NOW_PLAYING_ARTWORK_TARGET_PX,
        )
        if image is not None:
            self._artwork_ready(image)

    @Slot()
    @Slot(object)
    def _publish_immediately(self, _value: object | None = None) -> None:
        self._timeline_timer.stop()
        self._publish()

    @Slot(int)
    def _position_changed(self, _position_ms: int) -> None:
        if self._closed:
            return
        if not self._controller.playing:
            self._publish_immediately()
        elif not self._timeline_timer.isActive():
            self._timeline_timer.start()

    @Slot()
    def _publish(self, *, force: bool = False) -> None:
        if self._closed:
            return
        snapshot = self._snapshot()
        if not force and self._has_published and snapshot == self._last_published:
            return
        try:
            self._session.publish(snapshot)
        except Exception:
            self._disable_session("publish")
            return
        self._last_published = snapshot
        self._has_published = True

    def _disable_session(self, operation: str) -> None:
        logger.warning(
            "Could not %s the Host system-media session; playback will continue",
            operation,
            exc_info=True,
        )
        failed_session = self._session
        self._session = NullSystemMediaSession()
        try:
            failed_session.set_command_handler(None)
        except Exception:
            logger.debug(
                "Could not detach commands from the failed Host system-media session",
                exc_info=True,
            )
        try:
            failed_session.close()
        except Exception:
            logger.debug(
                "Could not close the failed Host system-media session",
                exc_info=True,
            )

    def _snapshot(self) -> SystemMediaSnapshot | None:
        track = self._controller.current_track
        entry_id = self._controller.current_entry_id
        if track is None or entry_id is None:
            return None
        playing = self._controller.playing
        return SystemMediaSnapshot(
            entry_id=entry_id,
            track_id=track.track_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            genre=track.genre,
            track_number=track.track_number,
            duration_ms=max(0, track.length_ms),
            position_ms=min(max(0, self._controller.position_ms), track.length_ms),
            playing=playing,
            can_play=not playing,
            can_pause=playing,
            can_next=True,
            can_previous=True,
            can_seek=track.length_ms > 0,
            volume_percent=self._controller.volume_percent,
            artwork=(
                self._artwork
                if self._artwork is not None
                and self._artwork.artwork_id == track.artwork_id
                else None
            ),
        )


def _artwork_resolution(width: int, height: int) -> tuple[int, int]:
    """Match iPodDB's largest-edge, then area, cover selection priority."""

    return (max(width, height), width * height)


__all__ = ["SystemMediaBridge"]
