"""Encoded media and identity-free source doubles for lyrics display tests."""

import base64
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThreadPool

from iOpenPod.app.lyrics_controller import LyricsController
from iOpenPod.app.media.lyrics import rewrite_lyrics
from iOpenPod.app.playback.backend import PlaybackSource, PlaybackSourceError
from iPodDB.library import Track

WORDS = "First line\n\nDeuxième ligne — 日本語 🎵\n<not markup> & text"


def media(name: str = "tone.mp3", lyrics: str = WORDS) -> bytes:
    path = Path(__file__).parents[1] / "fixtures" / "media" / f"{name}.b64"
    return rewrite_lyrics(base64.b64decode(path.read_bytes()), name, lyrics)


def finish_lyrics_workers(controller: LyricsController) -> None:
    """Finish file reads without delivering their queued results."""

    pool = controller.findChild(QThreadPool)
    assert pool is not None and pool.waitForDone(5000)


@dataclass
class MemorySource:
    payload: bytes
    file_name: str = "track.mp3"
    reads: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])

    @property
    def byte_count(self) -> int:
        return len(self.payload)

    def read_at(self, offset: int, length: int) -> bytes:
        self.reads.append((offset, length))
        return self.payload[offset : offset + length]


class SourceProvider:
    def __init__(self, sources: dict[int, PlaybackSource]) -> None:
        self.sources = sources
        self.opened: list[Track] = []

    def open_playback_source(self, track: Track) -> PlaybackSource:
        self.opened.append(track)
        source = self.sources.get(track.track_id)
        if source is None:
            raise PlaybackSourceError("Track disconnected")
        return source
