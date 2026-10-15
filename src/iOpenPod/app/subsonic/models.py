"""Domain models for OpenSubsonic server integration and playlist sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SubsonicSyncMode(StrEnum):
    """How Subsonic playlist tracks are synchronized with an existing iPod playlist."""

    MERGE = "merge"
    OVERWRITE = "overwrite"


@dataclass(frozen=True, slots=True)
class SubsonicPlaylist:
    """One playlist metadata record returned by OpenSubsonic getPlaylists."""

    playlist_id: str
    name: str
    comment: str = ""
    song_count: int = 0
    duration: int = 0
    created: str = ""


@dataclass(frozen=True, slots=True)
class SubsonicSong:
    """One track record returned inside an OpenSubsonic playlist."""

    song_id: str
    title: str
    artist: str = ""
    album: str = ""
    track: int | None = None
    year: int | None = None
    genre: str | None = None
    duration: int = 0
    cover_art: str | None = None


@dataclass(frozen=True, slots=True)
class SubsonicPlaylistMapping:
    """Mapping intent from a Subsonic playlist to an iPod playlist target."""

    subsonic_id: str
    subsonic_name: str
    target_ipod_id: int | None = None
    mode: SubsonicSyncMode = SubsonicSyncMode.MERGE


@dataclass(frozen=True, slots=True)
class SubsonicSyncResult:
    """Outcome summary of a Subsonic playlist sync pass."""

    playlists_synced: int
    tracks_matched: int
    tracks_unmatched: int
    errors: tuple[str, ...] = field(default_factory=tuple)
