"""Checked native facts absent from the source-neutral Library Snapshot."""

from dataclasses import dataclass

from iPodDB.library.playlists import Playlist
from iPodDB.SQLiteDB.genius import GeniusData


@dataclass(frozen=True, slots=True)
class SQLiteSource:
    """Caller-captured companion bytes, never filesystem authority."""

    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SQLiteGeniusTrack:
    """Bind one checked Library Track to its separate Genius identity."""

    track_id: int
    genius_id: int


@dataclass(frozen=True, slots=True)
class SQLiteGeniusMix:
    """Native Mix membership supplies possible starting Tracks."""

    container_id: int
    name: str
    track_ids: tuple[int, ...]
    seed_track_id: int | None = None


@dataclass(frozen=True, slots=True)
class SQLiteGeniusUpdate:
    """Replace graph and assignments; omitted Mix intent preserves native Mixes.

    ``mixes=None`` retains existing containers and their surviving assigned
    starting Tracks. An explicit tuple replaces the Mix set; ``()`` clears it.
    With ``mixes=None``, selective additions and removals preserve unmentioned
    native Mix records. Additions cannot overwrite retained container identities.
    """

    data: GeniusData
    tracks: tuple[SQLiteGeniusTrack, ...] = ()
    mixes: tuple[SQLiteGeniusMix, ...] | None = None
    # Selective collection management preserves every unmentioned native row.
    mix_additions: tuple[SQLiteGeniusMix, ...] = ()
    mix_removals: tuple[int, ...] = ()


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
    podcast: bool = False


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
    database_id: int = 0
    master_id: int = 0
    database_version: int = 111
    master_date_created: int = 0
    master_date_modified: int = 0
    normalize_podcasts: bool = False
