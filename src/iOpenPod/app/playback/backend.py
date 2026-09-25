"""Typed seam between playback policy and an audio engine adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import NewType, Protocol

from iPodDB.library import Track

PlaybackAttemptId = NewType("PlaybackAttemptId", int)


class PlaybackSourceError(Exception):
    """A Track cannot be exposed as a safe, seekable Playback Source."""


class PlaybackSource(Protocol):
    """Seekable, read-only Track bytes independent of an audio engine."""

    @property
    def byte_count(self) -> int: ...

    @property
    def file_name(self) -> str: ...

    def read_at(self, offset: int, length: int) -> bytes:
        """Read at most ``length`` bytes starting at ``offset``."""

        ...


class PlaybackSourceProvider(Protocol):
    """Open the current Library's Track through its authorized source."""

    def open_playback_source(self, track: Track) -> PlaybackSource: ...


@dataclass(frozen=True, slots=True)
class PlaybackFailure:
    """One user-relevant failure from the active Playback Backend."""

    attempt_id: PlaybackAttemptId
    track_id: int
    message: str
    error_type: str


class PlaybackBackend(Protocol):
    """Small transport interface implemented by an audio engine adapter."""

    def subscribe_playing_changed(
        self,
        callback: Callable[[PlaybackAttemptId, bool], None],
    ) -> None: ...

    def subscribe_position_changed(
        self,
        callback: Callable[[PlaybackAttemptId, int], None],
    ) -> None: ...

    def subscribe_finished(
        self,
        callback: Callable[[PlaybackAttemptId], None],
    ) -> None: ...

    def subscribe_failed(
        self,
        callback: Callable[[PlaybackFailure], None],
    ) -> None: ...

    def start(self, attempt_id: PlaybackAttemptId, track: Track) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def stop(self) -> None: ...

    def seek(self, position_ms: int) -> None: ...

    def set_volume(self, percent: int) -> None: ...

    def close(self) -> None: ...


__all__ = [
    "PlaybackAttemptId",
    "PlaybackBackend",
    "PlaybackFailure",
    "PlaybackSource",
    "PlaybackSourceError",
    "PlaybackSourceProvider",
]
