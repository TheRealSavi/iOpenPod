"""Lossless firmware sidecar records, independent of the Library contract."""

from dataclasses import dataclass
from enum import StrEnum


class PlaybackDateKind(StrEnum):
    LOCAL_MAC = "local_mac"
    UNIX = "unix"


@dataclass(frozen=True, slots=True)
class PlaybackEntry:
    play_count: int = 0
    last_played: int = 0
    bookmark_time_ms: int = 0
    rating: int | None = None
    skip_count: int = 0
    last_skipped: int = 0
    persistent_id: int | None = None
    date_kind: PlaybackDateKind = PlaybackDateKind.LOCAL_MAC
    # iTunesStats has a separate, incompletely understood 'skipped' value.
    skipped: int = 0
    unknown: bytes = b""


@dataclass(frozen=True, slots=True)
class PlaybackDocument:
    data: bytes
    entries: tuple[PlaybackEntry, ...]
    format: str

    def serialize(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class PositionalSidecar:
    data: bytes
    header_size: int
    entry_size: int
    byte_order: str
    rows: tuple[bytes, ...]

    def serialize(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class OTGPlaylistDocument:
    table: PositionalSidecar
    positions: tuple[int, ...]

    def serialize(self) -> bytes:
        return self.table.data


@dataclass(frozen=True, slots=True)
class PlaybackSidecar:
    """Captured filename and original bytes, without filesystem authority."""

    name: str
    data: bytes
