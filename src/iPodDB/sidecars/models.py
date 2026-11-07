"""Lossless firmware sidecar records, independent of the Library contract.

Dates, missing fields and explicit clears are distinct evidence. See
docs/research/classic-datetime-file-map-2026-11-06.md and docs/playback-sidecars.md.
"""

from dataclasses import dataclass
from enum import StrEnum


class PlaybackDateKind(StrEnum):
    """The codec's date coordinate, not an assertion about every Classic file."""

    LOCAL_MAC = "local_mac"
    UNIX = "unix"


@dataclass(frozen=True, slots=True)
class PlaybackEntry:
    """Playback deltas and date words before semantic Library reconciliation.

    LOCAL_MAC values retain calendar seconds from 1904, without a timezone/fold
    marker. UNIX is the supported iTunesStats interpretation. Date values do not
    order playback events reliably after clock changes, and counters are separate.
    Binary Play Counts replaces present dates, including backward values and zero
    clears; stats/plist merging retains its separate newest-nonzero Host policy.
    """

    play_count: int = 0
    # Raw coordinate selected by date_kind, not necessarily a Unix instant.
    # Zero is an explicit clear only under binary Play Counts reconciliation.
    last_played: int = 0
    bookmark_time_ms: int = 0
    rating: int | None = None
    skip_count: int = 0
    # None means the format/record has no date field; a present zero is distinct.
    last_skipped: int | None = None
    # Play Counts row byte +0x11: Host projection interprets 1 as played and 2
    # as unplayed. Retain all other raw values without assigning an override.
    played_marker: int | None = None
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
    trailing_data: bytes = b""

    def serialize(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class PositionalSidecar:
    data: bytes
    header_size: int
    entry_size: int
    byte_order: str
    rows: tuple[bytes, ...]
    trailing_data: bytes = b""

    def serialize(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class OTGPlaylistDocument:
    """Positional memberships; no datetime field is currently qualified.

    Unknown header/row bytes remain in table rather than receiving date meanings.
    """

    table: PositionalSidecar
    positions: tuple[int, ...]

    def serialize(self) -> bytes:
        return self.table.data


@dataclass(frozen=True, slots=True)
class PlaybackSidecar:
    """Captured filename and original bytes, without filesystem authority."""

    name: str
    data: bytes
