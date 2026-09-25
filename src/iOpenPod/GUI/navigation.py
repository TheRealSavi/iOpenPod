"""Stable application routes and their translated presentation copy."""

from enum import StrEnum
from typing import cast

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication


class PageId(StrEnum):
    """Stable route identifiers; labels remain localizable presentation data."""

    ALBUMS = "albums"
    ARTISTS = "artists"
    GENRES = "genres"
    TRACKS = "tracks"
    PLAYLISTS = "playlists"
    PHOTOS = "photos"
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


_PAGE_LABEL_SOURCES = cast(
    "dict[PageId, str]",
    {
        PageId.ALBUMS: QT_TRANSLATE_NOOP("Navigation", "Albums"),
        PageId.ARTISTS: QT_TRANSLATE_NOOP("Navigation", "Artists"),
        PageId.GENRES: QT_TRANSLATE_NOOP("Navigation", "Genres"),
        PageId.TRACKS: QT_TRANSLATE_NOOP("Navigation", "Tracks"),
        PageId.PLAYLISTS: QT_TRANSLATE_NOOP("Navigation", "Playlists"),
        PageId.PHOTOS: QT_TRANSLATE_NOOP("Navigation", "Photos"),
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
