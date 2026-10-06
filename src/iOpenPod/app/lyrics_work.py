"""Cancelable background read of one Track's embedded lyrics."""

from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Signal

from iOpenPod.app.media.lyrics_reader import read_embedded_lyrics

if TYPE_CHECKING:
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iPodDB.library import Track


class _LyricsSignals(QObject):
    finished = Signal(int, str, bool)


class LyricsReadWork(QRunnable):
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
