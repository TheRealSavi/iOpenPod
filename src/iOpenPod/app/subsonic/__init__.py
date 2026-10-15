"""Subsonic playlist sync support for iOpenPod."""

from .client import SubsonicClient, SubsonicConnectionError
from .controller import SubsonicController
from .credentials import SubsonicCredentialStore, SystemSubsonicCredentialStore
from .models import (
    SubsonicPlaylist,
    SubsonicPlaylistMapping,
    SubsonicSong,
    SubsonicSyncMode,
    SubsonicSyncResult,
)
from .settings import (
    SUBSONIC_PLAYLIST_IDS,
    SUBSONIC_PLAYLIST_MAPPINGS,
    SUBSONIC_URL,
    SUBSONIC_USERNAME,
    delete_subsonic_password,
    get_subsonic_password,
    set_subsonic_password,
)
from .sync import (
    index_library_tracks,
    match_subsonic_entries,
    normalize_match_key,
    sync_subsonic_playlists,
)

__all__ = [
    "SUBSONIC_PLAYLIST_IDS",
    "SUBSONIC_PLAYLIST_MAPPINGS",
    "SUBSONIC_URL",
    "SUBSONIC_USERNAME",
    "SubsonicClient",
    "SubsonicConnectionError",
    "SubsonicController",
    "SubsonicCredentialStore",
    "SubsonicPlaylist",
    "SubsonicPlaylistMapping",
    "SubsonicSong",
    "SubsonicSyncMode",
    "SubsonicSyncResult",
    "SystemSubsonicCredentialStore",
    "delete_subsonic_password",
    "get_subsonic_password",
    "index_library_tracks",
    "match_subsonic_entries",
    "normalize_match_key",
    "set_subsonic_password",
    "sync_subsonic_playlists",
]
