"""Immutable, source-neutral Playlist and Smart Playlist descriptions."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iPodDB.library.models import Track


class PlaylistKind(StrEnum):
    PLAYLIST = "playlist"
    SMART = "smart"
    FOLDER = "folder"


class PlaylistSortOrder(IntEnum):
    """Understood iPod Playlist display orders.

    Values match the MHYP field so an understood order can cross the semantic
    Library boundary without a second, loosely typed integer representation.
    """

    DEFAULT = 0
    MANUAL = 1
    TITLE = 3
    ALBUM = 4
    ARTIST = 5
    BITRATE = 6
    GENRE = 7
    KIND = 8
    DATE_MODIFIED = 9
    TRACK_NUMBER = 10
    SIZE = 11
    DURATION = 12
    YEAR = 13
    SAMPLE_RATE = 14
    COMMENT = 15
    DATE_ADDED = 16
    EQUALIZER = 17
    COMPOSER = 18
    PLAY_COUNT = 20
    LAST_PLAYED = 21
    DISC_NUMBER = 22
    RATING = 23
    RELEASE_DATE = 24
    BPM = 25
    GROUPING = 26
    CATEGORY = 27
    DESCRIPTION = 28


@dataclass(frozen=True, slots=True)
class UnsupportedPlaylistSortOrder:
    """An unknown MHYP sort value retained without assigning it semantics."""

    value: int

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 0xFFFFFFFF:
            raise ValueError("A Playlist sort value must fit an unsigned 32-bit field.")
        if any(order.value == self.value for order in PlaylistSortOrder):
            raise ValueError("Use PlaylistSortOrder for an understood sort value.")


type PlaylistSort = PlaylistSortOrder | UnsupportedPlaylistSortOrder


def playlist_sort_from_value(value: int) -> PlaylistSort:
    """Translate a native value while making unsupported values explicit."""

    try:
        return PlaylistSortOrder(value)
    except ValueError:
        return UnsupportedPlaylistSortOrder(value)


def playlist_sort_value(order: PlaylistSort) -> int:
    """Return the exact native value represented by a typed sort order."""

    return order.value


class SmartMatch(StrEnum):
    ALL = "all"
    ANY = "any"


class SmartField(StrEnum):
    TITLE = "title"
    ARTIST = "artist"
    ALBUM = "album"
    GENRE = "genre"
    YEAR = "year"
    RATING = "rating"
    PLAY_COUNT = "play_count"
    BITRATE = "bitrate"
    SAMPLE_RATE = "sample_rate"
    FILE_FORMAT = "file_format"
    TRACK_NUMBER = "track_number"
    SIZE = "size"
    DURATION = "duration"
    COMMENT = "comment"
    COMPOSER = "composer"
    DISC_NUMBER = "disc_number"
    CHECKED = "checked"
    COMPILATION = "compilation"
    BPM = "bpm"
    ARTWORK = "artwork"
    GROUPING = "grouping"
    DESCRIPTION = "description"
    CATEGORY = "category"
    SKIP_COUNT = "skip_count"
    ALBUM_ARTIST = "album_artist"
    SORT_TITLE = "sort_title"
    SORT_ALBUM = "sort_album"
    SORT_ARTIST = "sort_artist"
    SORT_ALBUM_ARTIST = "sort_album_artist"
    SORT_COMPOSER = "sort_composer"
    SORT_SHOW = "sort_show"
    PLAYLIST = "playlist"
    PURCHASED = "purchased"
    MEDIA_KIND = "media_kind"
    LOCATION = "location"
    DATE_MODIFIED = "date_modified"
    DATE_ADDED = "date_added"
    LAST_PLAYED = "last_played"
    LAST_SKIPPED = "last_skipped"


class SmartOperator(StrEnum):
    IS = "is"
    IS_NOT = "is_not"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    BEGINS_WITH = "begins_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    BETWEEN = "between"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    IN_LAST = "in_last"
    NOT_IN_LAST = "not_in_last"


class SmartLimitUnit(StrEnum):
    TRACKS = "tracks"
    MINUTES = "minutes"
    HOURS = "hours"
    MEGABYTES = "megabytes"
    GIGABYTES = "gigabytes"


class SmartLimitSort(StrEnum):
    RANDOM = "random"
    TITLE = "title"
    ALBUM = "album"
    ARTIST = "artist"
    GENRE = "genre"
    DATE_ADDED = "date_added"
    PLAY_COUNT = "play_count"
    LAST_PLAYED = "last_played"
    RATING = "rating"


class SmartMediaKind(StrEnum):
    """Media choices proven for the native Smart Playlist menu."""

    MUSIC = "music"
    MUSIC_VIDEO = "music_video"
    MOVIE = "movie"
    TV_SHOW = "tv_show"
    PODCAST = "podcast"
    AUDIOBOOK = "audiobook"
    VOICE_MEMO = "voice_memo"
    ITUNES_EXTRA = "itunes_extra"


class SmartLocation(StrEnum):
    """Location choices used by legacy iTunes Smart Playlist rules."""

    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class SmartPlaylistReference:
    """A typed reference to another Playlist's saved membership."""

    playlist_id: int


type SmartRuleValue = (
    str | int | SmartMediaKind | SmartLocation | SmartPlaylistReference
)


@dataclass(frozen=True, slots=True)
class SmartRule:
    """One understood comparison; ratings use the shared 0-100 scale."""

    field: SmartField
    operator: SmartOperator
    value: SmartRuleValue
    upper_value: SmartRuleValue | None = None


@dataclass(frozen=True, slots=True)
class UnsupportedSmartRule:
    """A preserved source condition which consumers must not evaluate or replace."""

    description: str = "This rule is not supported yet"


@dataclass(frozen=True, slots=True)
class SmartRuleGroup:
    """A recursive boolean expression; groups retain their own conjunction."""

    match: SmartMatch = SmartMatch.ALL
    rules: tuple[SmartRule | SmartRuleGroup | UnsupportedSmartRule, ...] = ()


@dataclass(frozen=True, slots=True)
class SmartPlaylistLimit:
    """Select an ordered, bounded set; descending has its ordinary sort meaning."""

    value: int
    unit: SmartLimitUnit
    sort: SmartLimitSort
    descending: bool = False


@dataclass(frozen=True, slots=True)
class SmartPlaylist:
    """Smart Playlist configuration, separate from its stored Track membership.

    ``editable`` is false when any source condition or preference cannot be
    represented faithfully. Consumers must keep such configurations intact.
    """

    rules: SmartRuleGroup = SmartRuleGroup()
    live_update: bool = True
    match_rules: bool = True
    checked_only: bool = False
    limit: SmartPlaylistLimit | None = None
    editable: bool = True


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    """One occurrence and its optional stored Playlist position.

    Ordinary positions are zero-based; Podcasts may retain native episode IDs.
    Moving retained occurrences need not replace their source position values:
    preparation derives positions from the final order and dataset semantics.
    """

    entry_id: str
    track_id: int
    position: int | None = None

    def __post_init__(self) -> None:
        if self.position is not None and not 0 <= self.position <= 0xFFFFFFFF:
            raise ValueError("A Playlist position must fit an unsigned 32-bit field.")


def playlist_entries(
    track_ids: Iterable[int], previous: tuple[PlaylistEntry, ...] = ()
) -> tuple[PlaylistEntry, ...]:
    """Keep matching occurrences in order and give new occurrences fresh identities.

    Callers that reorder particular duplicates should move the entries themselves.
    This helper is for constructing membership from a Track-only selection.
    """

    available: dict[int, deque[PlaylistEntry]] = defaultdict(deque)
    for entry in previous:
        available[entry.track_id].append(entry)
    entries = (
        available[track_id].popleft()
        if available[track_id]
        else PlaylistEntry(uuid4().hex, track_id)
        for track_id in track_ids
    )
    return tuple(
        replace(entry, position=position) for position, entry in enumerate(entries)
    )


def order_playlist_entries(
    entries: tuple[PlaylistEntry, ...],
    tracks: Iterable[Track],
    order: PlaylistSort,
) -> tuple[PlaylistEntry, ...]:
    """Apply one understood display order and refresh zero-based positions.

    Sorting is stable. Missing Track references remain at the end in their prior
    order so this helper never invents or drops Playlist occurrences.
    """

    ordered = list(entries)
    if isinstance(order, PlaylistSortOrder) and order not in (
        PlaylistSortOrder.DEFAULT,
        PlaylistSortOrder.MANUAL,
    ):
        track_index = {track.track_id: track for track in tracks}
        ordered.sort(
            key=lambda entry: (
                entry.track_id not in track_index,
                _playlist_sort_key(track_index.get(entry.track_id), order),
            )
        )
    return tuple(
        replace(entry, position=position) for position, entry in enumerate(ordered)
    )


def _playlist_sort_key(
    track: Track | None, order: PlaylistSortOrder
) -> tuple[str | int | float, ...]:
    if track is None:
        return ()

    def text(value: str) -> str:
        return value.casefold()

    metadata = track.metadata
    match order:
        case PlaylistSortOrder.TITLE:
            return (text(metadata.sort_title or track.title),)
        case PlaylistSortOrder.ALBUM:
            return (
                text(metadata.sort_album or track.album),
                metadata.disc_number,
                track.track_number,
            )
        case PlaylistSortOrder.ARTIST:
            return (
                text(metadata.sort_artist or track.artist),
                text(metadata.sort_album or track.album),
                metadata.disc_number,
                track.track_number,
            )
        case PlaylistSortOrder.BITRATE:
            return (track.bitrate_kbps,)
        case PlaylistSortOrder.GENRE:
            return (
                text(track.genre),
                text(metadata.sort_artist or track.artist),
                text(metadata.sort_album or track.album),
                track.track_number,
            )
        case PlaylistSortOrder.KIND:
            return (text(metadata.file_format),)
        case PlaylistSortOrder.DATE_MODIFIED:
            return (metadata.last_modified,)
        case PlaylistSortOrder.TRACK_NUMBER:
            return (metadata.disc_number, track.track_number)
        case PlaylistSortOrder.SIZE:
            return (track.size_bytes,)
        case PlaylistSortOrder.DURATION:
            return (track.length_ms,)
        case PlaylistSortOrder.YEAR:
            return (
                track.year,
                text(metadata.sort_artist or track.artist),
                text(metadata.sort_album or track.album),
            )
        case PlaylistSortOrder.SAMPLE_RATE:
            return (metadata.sample_rate_hz,)
        case PlaylistSortOrder.COMMENT:
            return (text(metadata.comment),)
        case PlaylistSortOrder.DATE_ADDED:
            return (metadata.date_added,)
        case PlaylistSortOrder.EQUALIZER:
            return (text(metadata.equalizer),)
        case PlaylistSortOrder.COMPOSER:
            return (text(metadata.sort_composer or metadata.composer),)
        case PlaylistSortOrder.PLAY_COUNT:
            return (track.play_count,)
        case PlaylistSortOrder.LAST_PLAYED:
            return (metadata.last_played,)
        case PlaylistSortOrder.DISC_NUMBER:
            return (metadata.disc_number, track.track_number)
        case PlaylistSortOrder.RATING:
            return (track.rating,)
        case PlaylistSortOrder.RELEASE_DATE:
            return (metadata.release_date,)
        case PlaylistSortOrder.BPM:
            return (metadata.bpm,)
        case PlaylistSortOrder.GROUPING:
            return (text(metadata.grouping),)
        case PlaylistSortOrder.CATEGORY:
            return (text(metadata.category),)
        case PlaylistSortOrder.DESCRIPTION:
            return (text(metadata.description),)
        case PlaylistSortOrder.DEFAULT | PlaylistSortOrder.MANUAL:
            return ()


@dataclass(frozen=True, slots=True)
class Playlist:
    """One semantic Playlist; ordered Track occurrences may repeat a Track ID.

    IDs are opaque and unique in their Library Snapshot. A ``None`` parent means
    the sidebar root. Folders can parent any kind, including other folders.
    ``system_managed`` is source metadata for presentation policy, not an editable
    value, so it does not participate in draft equality.
    """

    playlist_id: int
    name: str
    kind: PlaylistKind = PlaylistKind.PLAYLIST
    parent_id: int | None = None
    entries: tuple[PlaylistEntry, ...] = ()
    smart: SmartPlaylist | None = None
    description: str = ""
    sort_order: PlaylistSort = PlaylistSortOrder.DEFAULT
    system_managed: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.sort_order,
            PlaylistSortOrder | UnsupportedPlaylistSortOrder,
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("A Playlist needs a typed Playlist sort order.")

    @property
    def track_ids(self) -> tuple[int, ...]:
        return tuple(entry.track_id for entry in self.entries)
