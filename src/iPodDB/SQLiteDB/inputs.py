"""Checked native facts absent from the source-neutral Library Snapshot."""

from dataclasses import dataclass

from iPodDB.library.playlists import Playlist


@dataclass(frozen=True, slots=True)
class SQLiteSmartPreferences:
    live_update: int = 1
    check_rules: int = 1
    check_limits: int = 0
    limit_type: int = 2
    limit_sort: int = 2
    limit_value: int = 25
    checked_only: int = 0
    reverse_sort: int = 0


@dataclass(frozen=True, slots=True)
class SQLiteContainer:
    playlist: Playlist
    dataset: int = 3
    category: int = 0
    hidden: bool = False
    date_created: int = 0
    date_modified: int = 0
    preferences: SQLiteSmartPreferences | None = None
    criteria: bytes | None = None


@dataclass(frozen=True, slots=True)
class SQLiteChapter:
    track_id: int
    data: bytes


@dataclass(frozen=True, slots=True)
class SQLiteNativeMetadata:
    """One checked CDB generation, never an independently editable Library.

    None selects semantic-only containers for callers without a native document.
    An empty tuple means the checked document has no non-Master containers.
    """

    containers: tuple[SQLiteContainer, ...] | None = None
    chapters: tuple[SQLiteChapter, ...] = ()
