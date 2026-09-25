"""Typed seam for Host Now Playing metadata and transport commands."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SystemMediaCommandKind(StrEnum):
    """Transport intents that a Host media surface can send to iOpenPod."""

    PLAY = "play"
    PAUSE = "pause"
    TOGGLE_PLAY_PAUSE = "toggle_play_pause"
    NEXT = "next"
    PREVIOUS = "previous"
    SEEK = "seek"
    SET_VOLUME = "set_volume"


@dataclass(frozen=True, slots=True)
class SystemMediaCommand:
    """One transport intent received from the Host."""

    kind: SystemMediaCommandKind
    position_ms: int | None = None
    volume_percent: int | None = None

    def __post_init__(self) -> None:
        if self.kind is SystemMediaCommandKind.SEEK:
            if self.position_ms is None:
                raise ValueError("A system-media seek command requires a position")
            if self.volume_percent is not None:
                raise ValueError("A system-media seek command cannot set volume")
            return
        if self.kind is SystemMediaCommandKind.SET_VOLUME:
            if self.volume_percent is None:
                raise ValueError("A system-media volume command requires a volume")
            if not 0 <= self.volume_percent <= 100:
                raise ValueError("System-media volume must be between 0 and 100")
            if self.position_ms is not None:
                raise ValueError("A system-media volume command cannot seek")
            return
        if self.position_ms is not None or self.volume_percent is not None:
            raise ValueError("Only seek and volume system-media commands accept values")


@dataclass(frozen=True, slots=True)
class SystemMediaArtwork:
    """Bounded, platform-neutral RGB artwork published with a Track snapshot."""

    cache_key: str
    artwork_id: int
    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if not self.cache_key:
            raise ValueError("System-media artwork requires a cache key")
        if self.artwork_id <= 0:
            raise ValueError("System-media artwork requires a positive artwork ID")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("System-media artwork dimensions must be positive")
        expected = self.width * self.height * 3
        if len(self.rgb888) != expected:
            raise ValueError(
                f"System-media artwork has {len(self.rgb888)} RGB bytes; "
                f"expected {expected}"
            )


@dataclass(frozen=True, slots=True)
class SystemMediaSnapshot:
    """Controller-owned state published to one Host media integration."""

    entry_id: int
    track_id: int
    title: str
    artist: str
    album: str
    genre: str
    track_number: int
    duration_ms: int
    position_ms: int
    playing: bool
    can_play: bool
    can_pause: bool
    can_next: bool
    can_previous: bool
    can_seek: bool
    volume_percent: int = 100
    artwork: SystemMediaArtwork | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.volume_percent <= 100:
            raise ValueError("System-media volume must be between 0 and 100")


SystemMediaCommandHandler = Callable[[SystemMediaCommand], None]


class SystemMediaSession(Protocol):
    """Optional Host adapter that never owns audio playback or Queue policy."""

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None: ...

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None: ...

    def seeked(self, position_ms: int) -> None: ...

    def close(self) -> None: ...


class NullSystemMediaSession:
    """No-op session for unsupported Hosts or unavailable native facilities."""

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None:
        del handler

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        del snapshot

    def seeked(self, position_ms: int) -> None:
        del position_ms

    def close(self) -> None:
        return


__all__ = [
    "NullSystemMediaSession",
    "SystemMediaArtwork",
    "SystemMediaCommand",
    "SystemMediaCommandHandler",
    "SystemMediaCommandKind",
    "SystemMediaSession",
    "SystemMediaSnapshot",
]
