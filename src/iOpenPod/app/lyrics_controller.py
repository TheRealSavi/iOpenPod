"""Lazy lyrics for the Player's current Track, independent of audio playback."""

from __future__ import annotations

from enum import Enum, auto
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from iOpenPod.app.media.lyrics_reader import read_embedded_lyrics

if TYPE_CHECKING:
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iOpenPod.app.playback_controller import PlaybackController
    from iPodDB.library import Track


class LyricsState(Enum):
    NO_TRACK = auto()
    NOT_LOADED = auto()
    LOADING = auto()
    READY = auto()
    UNAVAILABLE = auto()


class _LyricsSignals(QObject):
    finished = Signal(int, str, bool)


class _LyricsWork(QRunnable):
    def __init__(
        self, token: int, provider: PlaybackSourceProvider, track: Track
    ) -> None:
        super().__init__()
        self.token = token
        self.provider = provider
        self.track = track
        self.cancelled = Event()
        self.signals = _LyricsSignals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise ValueError("Lyrics request was cancelled.")

        try:
            checkpoint()
            source = self.provider.open_playback_source(self.track)
            text = read_embedded_lyrics(source, checkpoint=checkpoint)
        except Exception:
            self.signals.finished.emit(self.token, "", False)
        else:
            self.signals.finished.emit(self.token, text, True)


class LyricsController(QObject):
    """Keep lyric reads off the GUI thread and reject obsolete worker results."""

    changed = Signal()

    def __init__(
        self,
        playback: PlaybackController,
        provider: PlaybackSourceProvider,
        workspace: LibraryWorkspace,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._playback = playback
        self._provider = provider
        self._workspace = workspace
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[int, _LyricsWork] = {}
        self._token = 0
        self._active = False
        self._closed = False
        self._text = ""
        self._state = LyricsState.NO_TRACK
        playback.currentTrackChanged.connect(self._track_changed)
        self._track_changed()

    @property
    def text(self) -> str:
        return self._text

    @property
    def state(self) -> LyricsState:
        return self._state

    def set_active(self, active: bool) -> None:
        """Read file tags only when the Lyrics tab is visible."""
        self._active = active
        self._load_if_needed()

    @Slot()
    def _track_changed(self) -> None:
        if self._closed:
            return
        self._cancel_jobs()
        self._token += 1
        track = self._playback.current_track
        self._text = "" if track is None else track.metadata.lyrics
        self._state = (
            LyricsState.NO_TRACK
            if track is None
            else LyricsState.READY
            if self._text or self._lyrics_cleared(track)
            else LyricsState.NOT_LOADED
        )
        self.changed.emit()
        self._load_if_needed()

    def _lyrics_cleared(self, track: Track) -> bool:
        snapshot = self._workspace.snapshot
        if snapshot is None or self._workspace.track(track.track_id) != track:
            return False
        original = next(
            (item for item in snapshot.tracks if item.track_id == track.track_id), None
        )
        return original is not None and (
            original.metadata.lyrics != track.metadata.lyrics
            or (original.metadata.has_lyrics and not track.metadata.has_lyrics)
        )

    def _load_if_needed(self) -> None:
        track = self._playback.current_track
        if (
            self._closed
            or not self._active
            or track is None
            or self._state is not LyricsState.NOT_LOADED
        ):
            return
        work = _LyricsWork(self._token, self._provider, track)
        work.signals.finished.connect(self._finished)
        self._jobs[self._token] = work
        self._state = LyricsState.LOADING
        self.changed.emit()
        self._pool.start(work)

    @Slot(int, str, bool)
    def _finished(self, token: int, text: str, succeeded: bool) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token:
            return
        self._text = text
        self._state = LyricsState.READY if succeeded else LyricsState.UNAVAILABLE
        self.changed.emit()

    def _cancel_jobs(self) -> None:
        for work in self._jobs.values():
            work.cancelled.set()

    def shutdown(self) -> None:
        self._closed = True
        self._cancel_jobs()
        self._pool.waitForDone()
        self._jobs.clear()
