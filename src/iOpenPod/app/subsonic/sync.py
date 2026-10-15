"""Playlist matching and synchronization logic between Subsonic and iPod."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from iPodDB.library import PlaylistKind, Track

from .models import (
    SubsonicPlaylistMapping,
    SubsonicSong,
    SubsonicSyncMode,
    SubsonicSyncResult,
)

if TYPE_CHECKING:
    from iOpenPod.app.library_workspace import LibraryWorkspace

    from .client import SubsonicClient

logger = logging.getLogger(__name__)

# Transliteration mapping for smart quotes and typographical dashes.
_PUNCT_MAP = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    0x2013: "-",
    0x2014: "-",
}


def normalize_match_key(title: str, artist: str) -> tuple[str, str]:
    """Build a normalized (title, artist) key for fuzzy track matching.

    Transliterates smart punctuation, folds to lowercase, filters out non-alphanumeric
    characters, and collapses whitespace.
    """

    def _norm(text: str) -> str:
        text = (text or "").translate(_PUNCT_MAP).lower()
        cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in text)
        return " ".join(cleaned.split())

    return (_norm(title), _norm(artist))


def index_library_tracks(
    tracks: tuple[Track, ...],
) -> dict[tuple[str, str], int]:
    """Build a lookup index from (normalized_title, normalized_artist) to track_id."""
    index: dict[tuple[str, str], int] = {}
    for track in tracks:
        key = normalize_match_key(track.title, track.artist)
        if key != ("", "") and key not in index:
            index[key] = track.track_id
    return index


def match_subsonic_entries(
    entries: tuple[SubsonicSong, ...],
    track_index: dict[tuple[str, str], int],
) -> tuple[tuple[int, ...], int]:
    """Match Subsonic song entries against indexed library tracks.

    Returns:
        (matched_track_ids, unmatched_count)
    """
    matched: list[int] = []
    unmatched = 0
    for entry in entries:
        key = normalize_match_key(entry.title, entry.artist)
        track_id = track_index.get(key)
        if track_id is not None:
            matched.append(track_id)
        else:
            unmatched += 1
    return tuple(matched), unmatched


def sync_subsonic_playlists(
    workspace: LibraryWorkspace,
    client: SubsonicClient,
    mappings: tuple[SubsonicPlaylistMapping, ...],
) -> SubsonicSyncResult:
    """Execute playlist synchronization for the given mappings against the workspace."""
    if not mappings:
        return SubsonicSyncResult(playlists_synced=0, tracks_matched=0, tracks_unmatched=0)

    track_index = index_library_tracks(workspace.tracks)
    playlists_synced = 0
    total_matched = 0
    total_unmatched = 0
    errors: list[str] = []

    for mapping in mappings:
        try:
            entries = client.get_playlist(mapping.subsonic_id)
        except Exception as exc:
            err_msg = f"Failed to fetch Subsonic playlist '{mapping.subsonic_name}': {exc}"
            logger.warning(err_msg)
            errors.append(err_msg)
            continue

        matched_ids, unmatched = match_subsonic_entries(entries, track_index)
        total_matched += len(matched_ids)
        total_unmatched += unmatched

        if not matched_ids:
            logger.info(
                "Subsonic playlist '%s' has no matching tracks in iPod library (dropped)",
                mapping.subsonic_name,
            )
            continue

        try:
            if mapping.target_ipod_id is None:
                # Create a new playlist
                workspace.create(
                    kind=PlaylistKind.PLAYLIST,
                    name=mapping.subsonic_name,
                    track_ids=matched_ids,
                )
                playlists_synced += 1
            else:
                existing = workspace.playlist(mapping.target_ipod_id)
                if existing is None:
                    # Fallback to create if target no longer exists
                    workspace.create(
                        kind=PlaylistKind.PLAYLIST,
                        name=mapping.subsonic_name,
                        track_ids=matched_ids,
                    )
                    playlists_synced += 1
                elif mapping.mode == SubsonicSyncMode.OVERWRITE:
                    workspace.set_tracks(mapping.target_ipod_id, matched_ids)
                    playlists_synced += 1
                else:  # MERGE mode
                    existing_track_ids = tuple(
                        entry.track_id for entry in existing.entries
                    )
                    existing_set = set(existing_track_ids)
                    combined = existing_track_ids + tuple(
                        tid for tid in matched_ids if tid not in existing_set
                    )
                    workspace.set_tracks(mapping.target_ipod_id, combined)
                    playlists_synced += 1
        except Exception as exc:
            err_msg = f"Could not apply playlist '{mapping.subsonic_name}': {exc}"
            logger.error(err_msg, exc_info=True)
            errors.append(err_msg)

    return SubsonicSyncResult(
        playlists_synced=playlists_synced,
        tracks_matched=total_matched,
        tracks_unmatched=total_unmatched,
        errors=tuple(errors),
    )
