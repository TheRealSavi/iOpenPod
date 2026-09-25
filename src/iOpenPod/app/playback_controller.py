"""Runtime Playback Queue, History, and audio-engine orchestration."""

from PySide6.QtCore import QObject, Signal, Slot

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.playback_models import (
    PlaybackEntry,
    PlaybackHistoryModel,
    PlaybackQueueModel,
)
from iOpenPod.app.playback.backend import (
    PlaybackAttemptId,
    PlaybackBackend,
    PlaybackFailure,
)
from iPodDB.library import Track

_DEFAULT_VOLUME_PERCENT = 64


class PlaybackController(QObject):
    """Coordinate current Track, Playback Queue, and Playback History state."""

    currentTrackChanged = Signal(object)
    playingChanged = Signal(bool)
    positionChanged = Signal(int)
    seeked = Signal(int)
    volumeChanged = Signal(int)
    playbackFailed = Signal(object)

    def __init__(
        self,
        backend: PlaybackBackend,
        parent: QObject | None = None,
        *,
        workspace: LibraryWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self.queue_model = PlaybackQueueModel(
            self,
            workspace=workspace,
            insert_tracks=self.insert_tracks,
        )
        self.history_model = PlaybackHistoryModel(self, workspace=workspace)
        self._current_entry: PlaybackEntry | None = None
        self._playing = False
        self._position_ms = 0
        self._next_entry_id = 1
        self._next_attempt_id = 1
        self._active_attempt_id: PlaybackAttemptId | None = None
        self._volume_percent = _DEFAULT_VOLUME_PERCENT
        self._failed_current = False
        self._closed = False
        backend.subscribe_playing_changed(self._backend_playing_changed)
        backend.subscribe_position_changed(self._backend_position_changed)
        backend.subscribe_finished(self._backend_finished)
        backend.subscribe_failed(self._backend_failed)
        backend.set_volume(self._volume_percent)

    @property
    def current_track(self) -> Track | None:
        entry = self._current_entry
        return None if entry is None else entry.track

    @property
    def current_entry_id(self) -> int | None:
        entry = self._current_entry
        return None if entry is None else entry.entry_id

    @property
    def next_entry(self) -> PlaybackEntry | None:
        """Inspect the next occurrence using the same policy as Next."""

        return self._next_history_entry() or self.queue_model.entry_at(0)

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def volume_percent(self) -> int:
        return self._volume_percent

    def enqueue(self, track: Track) -> None:
        self.insert_tracks((track,), self.queue_model.rowCount())

    def play_next(self, tracks: tuple[Track, ...]) -> bool:
        """Place ordered occurrences atop the Queue without interrupting playback."""

        return self.insert_tracks(tracks, 0)

    def insert_tracks(self, tracks: tuple[Track, ...], row: int) -> bool:
        """Insert Track occurrences at one Queue position and start an idle Queue."""

        if not tracks:
            return False
        entries = tuple(self._new_entry(track) for track in tracks)
        self.queue_model.insert_entries(row, entries)
        if self._current_entry is None:
            self._start_next_queued_track()
        return True

    def play_now(self, tracks: tuple[Track, ...]) -> bool:
        """Start the first dropped Track and place the remainder atop the Queue."""

        if not tracks:
            return False
        entries = tuple(self._new_entry(track) for track in tracks)
        current, remaining = entries[0], entries[1:]
        self.queue_model.insert_entries(0, remaining)
        self.history_model.record(current)
        self._set_current_entry(current)
        return True

    def remove_queue_entry(self, entry_id: int) -> bool:
        return self.queue_model.remove_entry(entry_id)

    def clear_queue(self) -> None:
        self.queue_model.clear()

    def clear_history(self) -> None:
        """Forget played occurrences while preserving the current Track and Queue."""

        self.history_model.clear()

    def move_queue_entry(self, source_row: int, destination_row: int) -> bool:
        return self.queue_model.move_entry(source_row, destination_row)

    def toggle_play_pause(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        """Start or resume playback without toggling an already-playing Track."""

        if self._current_entry is None:
            self._start_next_queued_track()
            return
        if self._playing:
            return
        if self._failed_current:
            self._failed_current = False
            self._start_backend(self._current_entry.track)
            return
        self._backend.play()

    def pause(self) -> None:
        """Pause playback without starting an already-paused Track."""

        if self._current_entry is not None and self._playing:
            self._backend.pause()

    def clear_session(self) -> None:
        self.queue_model.clear()
        self._clear_current()
        self.history_model.clear()
        self._next_entry_id = 1

    def reconcile_library(self, tracks: tuple[Track, ...]) -> None:
        tracks_by_id = {track.track_id: track for track in tracks}
        current = self._current_entry
        self.queue_model.reconcile_tracks(tracks_by_id)
        self.history_model.reconcile_tracks(tracks_by_id)
        if current is None:
            return
        replacement = tracks_by_id.get(current.track.track_id)
        if replacement is None:
            self._clear_current()
            self._start_next_queued_track()
            return
        self._current_entry = PlaybackEntry(current.entry_id, replacement)
        self.history_model.set_current_entry(current.entry_id)
        if replacement != current.track:
            self.currentTrackChanged.emit(replacement)
        bounded_position = min(self._position_ms, replacement.length_ms)
        if bounded_position != self._position_ms:
            self._position_ms = bounded_position
            self.positionChanged.emit(bounded_position)

    def seek(self, position_ms: int) -> None:
        track = self.current_track
        bounded = 0 if track is None else min(max(0, position_ms), track.length_ms)
        self._set_position(bounded)
        if track is not None:
            self._backend.seek(bounded)
            self.seeked.emit(bounded)

    def set_volume(self, percent: int) -> None:
        bounded = min(100, max(0, percent))
        if bounded == self._volume_percent:
            return
        self._volume_percent = bounded
        self._backend.set_volume(bounded)
        self.volumeChanged.emit(bounded)

    def previous(self) -> None:
        entry = self._current_entry
        if entry is None:
            return
        if self._position_ms > 10_000:
            self.seek(0)
            return
        row = self.history_model.row_for_entry_id(entry.entry_id)
        older = self.history_model.entry_at(row + 1) if row is not None else None
        if older is None:
            self.seek(0)
            return
        self._set_current_entry(older)

    def _next_history_entry(self) -> PlaybackEntry | None:
        entry = self._current_entry
        if entry is not None:
            row = self.history_model.row_for_entry_id(entry.entry_id)
            return (
                self.history_model.entry_at(row - 1)
                if row is not None and row > 0
                else None
            )
        return None

    def next(self) -> None:
        newer = self._next_history_entry()
        if newer is not None:
            self._set_current_entry(newer)
            return
        if not self._start_next_queued_track():
            self._clear_current()

    def finish_current(self) -> None:
        self.next()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.clear_session()
        self._backend.close()

    def _start_next_queued_track(self) -> bool:
        entry = self.queue_model.take_first()
        if entry is None:
            return False
        self.history_model.record(entry)
        self._set_current_entry(entry)
        return True

    def _new_entry(self, track: Track) -> PlaybackEntry:
        entry = PlaybackEntry(self._next_entry_id, track)
        self._next_entry_id += 1
        return entry

    def _set_current_entry(self, entry: PlaybackEntry) -> None:
        was_playing = self._playing
        self._current_entry = entry
        # Observers of the new Playback Entry must never inherit the previous
        # Track's clock or playing state, even before the decoder starts.
        self._position_ms = 0
        self._playing = False
        self.history_model.set_current_entry(entry.entry_id)
        self._failed_current = False
        self.currentTrackChanged.emit(entry.track)
        self.positionChanged.emit(0)
        if was_playing:
            self.playingChanged.emit(False)
        self._start_backend(entry.track)

    def _clear_current(self) -> None:
        if (
            self._current_entry is None
            and self._active_attempt_id is None
            and not self._playing
            and self._position_ms == 0
        ):
            return
        self._current_entry = None
        self._active_attempt_id = None
        self.history_model.set_current_entry(None)
        self._failed_current = False
        self.currentTrackChanged.emit(None)
        self._set_position(0, force=True)
        self._set_playing(False)
        self._backend.stop()

    def _start_backend(self, track: Track) -> None:
        attempt_id = PlaybackAttemptId(self._next_attempt_id)
        self._next_attempt_id += 1
        self._active_attempt_id = attempt_id
        self._backend.start(attempt_id, track)

    @Slot(int, bool)
    def _backend_playing_changed(
        self,
        attempt_id: PlaybackAttemptId,
        playing: bool,
    ) -> None:
        if attempt_id != self._active_attempt_id:
            return
        self._set_playing(playing and self._current_entry is not None)

    @Slot(int, int)
    def _backend_position_changed(
        self,
        attempt_id: PlaybackAttemptId,
        position_ms: int,
    ) -> None:
        if attempt_id != self._active_attempt_id:
            return
        track = self.current_track
        if track is None:
            return
        self._set_position(min(max(0, position_ms), track.length_ms))

    @Slot(int)
    def _backend_finished(self, attempt_id: PlaybackAttemptId) -> None:
        if attempt_id == self._active_attempt_id and self._current_entry is not None:
            self.finish_current()

    @Slot(object)
    def _backend_failed(self, value: object) -> None:
        track = self.current_track
        if (
            not isinstance(value, PlaybackFailure)
            or track is None
            or value.attempt_id != self._active_attempt_id
            or value.track_id != track.track_id
        ):
            return
        self._failed_current = True
        self._set_playing(False)
        self.playbackFailed.emit(value)

    def _set_position(self, position_ms: int, *, force: bool = False) -> None:
        if position_ms == self._position_ms and not force:
            return
        self._position_ms = position_ms
        self.positionChanged.emit(position_ms)

    def _set_playing(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        self.playingChanged.emit(playing)


__all__ = ["PlaybackController"]
