"""Stable application routes and their translated presentation copy."""

from enum import StrEnum
from typing import cast

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from device_registry import DeviceProfile, FeatureSupport
from iOpenPod.app import developer_flags


class PageId(StrEnum):
    """Stable route identifiers; labels remain localizable presentation data."""

    START = "start"
    DEVICE_SUMMARY = "device-summary"
    ALBUMS = "albums"
    ARTISTS = "artists"
    GENRES = "genres"
    TRACKS = "tracks"
    PLAYLISTS = "playlists"
    GENIUS = "genius"
    GAMES = "games"
    PHOTOS = "photos"
    CALENDAR = "calendar"
    ALARMS = "alarms"
    PODCASTS = "podcasts"
    AUDIOBOOKS = "audiobooks"
    MOVIES = "movies"
    TV_SHOWS = "tv-shows"
    MUSIC_VIDEOS = "music-videos"
    VIDEOS = "videos"
    SYNESTHESIA = "synesthesia"
    BACKUPS = "backups"
    NORMALIZE_TAGS = "normalize-tags"
    SETTINGS = "settings"


_VIDEO_PAGES = frozenset(
    {PageId.MOVIES, PageId.TV_SHOWS, PageId.MUSIC_VIDEOS, PageId.VIDEOS}
)
_LIBRARY_PAGES = _VIDEO_PAGES | frozenset(
    {
        PageId.ALBUMS,
        PageId.ARTISTS,
        PageId.GENRES,
        PageId.TRACKS,
        PageId.PLAYLISTS,
        PageId.GENIUS,
        PageId.GAMES,
        PageId.PHOTOS,
        PageId.CALENDAR,
        PageId.ALARMS,
        PageId.PODCASTS,
        PageId.AUDIOBOOKS,
    }
)


def page_supported(page_id: PageId, profile: DeviceProfile | None) -> bool:
    """Share page availability across Library navigation styles."""

    if page_id is PageId.START:
        return profile is None
    if page_id is PageId.ALARMS and not developer_flags.ENABLE_EXTRAS_PAGES:
        return False
    if page_id in _LIBRARY_PAGES and profile is None:
        return False
    if page_id is PageId.GAMES:
        return profile is not None and profile.capabilities.supports_games
    if page_id is PageId.GENIUS:
        return profile is not None and (
            profile.capabilities.genius.playlists is not FeatureSupport.UNSUPPORTED
            or profile.capabilities.genius.mixes is not FeatureSupport.UNSUPPORTED
        )
    if page_id in _VIDEO_PAGES:
        return profile is not None and profile.capabilities.video.supported
    if page_id is PageId.PHOTOS:
        return profile is not None and profile.capabilities.artwork.supports_photos
    if page_id is PageId.PODCASTS:
        return profile is not None and profile.capabilities.audio.supports_podcasts
    if page_id is PageId.CALENDAR:
        return profile is not None and (
            profile.capabilities.extras.calendar is FeatureSupport.SUPPORTED
            or profile.capabilities.extras.todos is FeatureSupport.SUPPORTED
        )
    if page_id is PageId.ALARMS:
        return profile is not None and (
            profile.capabilities.extras.alarms is FeatureSupport.SUPPORTED
            or profile.capabilities.extras.sleep_timer is FeatureSupport.SUPPORTED
        )
    return True


_PAGE_LABEL_SOURCES = cast(
    "dict[PageId, str]",
    {
        PageId.START: QT_TRANSLATE_NOOP("Navigation", "Welcome"),
        PageId.DEVICE_SUMMARY: QT_TRANSLATE_NOOP("Navigation", "Device Summary"),
        PageId.ALBUMS: QT_TRANSLATE_NOOP("Navigation", "Albums"),
        PageId.ARTISTS: QT_TRANSLATE_NOOP("Navigation", "Artists"),
        PageId.GENRES: QT_TRANSLATE_NOOP("Navigation", "Genres"),
        PageId.TRACKS: QT_TRANSLATE_NOOP("Navigation", "Tracks"),
        PageId.PLAYLISTS: QT_TRANSLATE_NOOP("Navigation", "Playlists"),
        PageId.GENIUS: QT_TRANSLATE_NOOP("Navigation", "Genius"),
        PageId.GAMES: QT_TRANSLATE_NOOP("Navigation", "Games"),
        PageId.PHOTOS: QT_TRANSLATE_NOOP("Navigation", "Photos"),
        PageId.CALENDAR: QT_TRANSLATE_NOOP("Navigation", "Calendar"),
        PageId.ALARMS: QT_TRANSLATE_NOOP("Navigation", "Alarms"),
        PageId.PODCASTS: QT_TRANSLATE_NOOP("Navigation", "Podcasts"),
        PageId.AUDIOBOOKS: QT_TRANSLATE_NOOP("Navigation", "Audiobooks"),
        PageId.MOVIES: QT_TRANSLATE_NOOP("Navigation", "Movies"),
        PageId.TV_SHOWS: QT_TRANSLATE_NOOP("Navigation", "TV Shows"),
        PageId.MUSIC_VIDEOS: QT_TRANSLATE_NOOP("Navigation", "Music Videos"),
        PageId.VIDEOS: QT_TRANSLATE_NOOP("Navigation", "Videos"),
        PageId.SYNESTHESIA: QT_TRANSLATE_NOOP("Navigation", "Synesthesia"),
        PageId.BACKUPS: QT_TRANSLATE_NOOP("Navigation", "Backups"),
        PageId.NORMALIZE_TAGS: QT_TRANSLATE_NOOP("Navigation", "Normalize Tags"),
        PageId.SETTINGS: QT_TRANSLATE_NOOP("Navigation", "Settings"),
    },
)

_PLACEHOLDER_DESCRIPTION_SOURCES = cast(
    "dict[PageId, str]",
    {
        PageId.ARTISTS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Artist browsing will project the iPod Library through a dedicated model.",
        ),
        PageId.GENRES: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Genre browsing will reuse the library grid and Track list surfaces.",
        ),
        PageId.PLAYLISTS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Playlist browsing and editing will be connected through an Application Layer module.",
        ),
        PageId.AUDIOBOOKS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Audiobook presentation is reserved without assuming Active iPod capabilities.",
        ),
        PageId.MOVIES: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Movie presentation is reserved without assuming Active iPod capabilities.",
        ),
        PageId.TV_SHOWS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "TV Show presentation is reserved without assuming Active iPod capabilities.",
        ),
        PageId.MUSIC_VIDEOS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Music Video presentation is reserved without assuming Active iPod capabilities.",
        ),
        PageId.VIDEOS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Video presentation is reserved without assuming Active iPod capabilities.",
        ),
        PageId.NORMALIZE_TAGS: QT_TRANSLATE_NOOP(
            "PlaceholderPage",
            "Tag analysis and review will appear here before any metadata is changed.",
        ),
    },
)

_FUTURE_PAGE_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP(
        "PlaceholderPage",
        "This page is reserved for a future application workflow.",
    ),
)


def page_label(page_id: PageId) -> str:
    """Return the translated human label for one stable route."""

    return QCoreApplication.translate("Navigation", _PAGE_LABEL_SOURCES[page_id])


def placeholder_description(page_id: PageId) -> str:
    """Explain an unfinished route without inventing unavailable behavior."""

    source = _PLACEHOLDER_DESCRIPTION_SOURCES.get(page_id, _FUTURE_PAGE_SOURCE)
    return QCoreApplication.translate("PlaceholderPage", source)
