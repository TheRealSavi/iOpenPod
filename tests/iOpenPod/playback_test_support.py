"""Shared typed Playback Backend fake for application and GUI tests."""

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from iOpenPod.app.playback.backend import PlaybackAttemptId, PlaybackFailure
from iPodDB.library import Track


class FakePlaybackBackend(QObject):
    """Synchronous backend with explicit hooks for backend-originated events."""

    playingChanged = Signal(int, bool)
    positionChanged = Signal(int, int)
    finished = Signal(int)
    failed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.started: list[Track] = []
        self.started_attempt_ids: list[PlaybackAttemptId] = []
        self.seeks: list[int] = []
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.volume_percent = -1
        self.current_track: Track | None = None
        self.current_attempt_id: PlaybackAttemptId | None = None
        self.closed = False

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
        self.current_attempt_id = attempt_id
        self.current_track = track
        self.started_attempt_ids.append(attempt_id)
        self.started.append(track)
        self.positionChanged.emit(attempt_id, 0)
        self.playingChanged.emit(attempt_id, True)

    def play(self) -> None:
        self.play_calls += 1
        if self.current_attempt_id is not None:
            self.playingChanged.emit(self.current_attempt_id, True)

    def pause(self) -> None:
        self.pause_calls += 1
        if self.current_attempt_id is not None:
            self.playingChanged.emit(self.current_attempt_id, False)

    def stop(self) -> None:
        self.stop_calls += 1
        attempt_id = self.current_attempt_id
        self.current_attempt_id = None
        self.current_track = None
        if attempt_id is not None:
            self.playingChanged.emit(attempt_id, False)

    def seek(self, position_ms: int) -> None:
        self.seeks.append(position_ms)
        self.emit_position(position_ms)

    def set_volume(self, percent: int) -> None:
        self.volume_percent = percent

    def close(self) -> None:
        self.closed = True

    def emit_playing(
        self,
        playing: bool,
        *,
        attempt_id: PlaybackAttemptId | None = None,
    ) -> None:
        resolved = self._resolve_attempt_id(attempt_id)
        self.playingChanged.emit(resolved, playing)

    def emit_position(
        self,
        position_ms: int,
        *,
        attempt_id: PlaybackAttemptId | None = None,
    ) -> None:
        resolved = self._resolve_attempt_id(attempt_id)
        self.positionChanged.emit(resolved, position_ms)

    def finish(self, *, attempt_id: PlaybackAttemptId | None = None) -> None:
        self.finished.emit(self._resolve_attempt_id(attempt_id))

    def fail(self, failure: PlaybackFailure) -> None:
        self.failed.emit(failure)

    def _resolve_attempt_id(
        self,
        attempt_id: PlaybackAttemptId | None,
    ) -> PlaybackAttemptId:
        resolved = attempt_id if attempt_id is not None else self.current_attempt_id
        if resolved is None:
            raise AssertionError("The fake backend has no current playback attempt")
        return resolved


__all__ = ["FakePlaybackBackend"]
