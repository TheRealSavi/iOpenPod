"""Structural Genius Playlist repairs for explicitly deleted Library Tracks."""

from dataclasses import replace

from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.playlists import Playlist, PlaylistKind


def reconcile_genius_playlists(
    original: LibrarySnapshot, desired: LibrarySnapshot
) -> LibrarySnapshot:
    """Prune deleted occurrences, replace lost known seeds, and omit emptied rows.

    Unaffected collections, including empty ones, retain their state. Unknown seeds
    stay opaque. This does not authorize arbitrary membership or seed editing;
    ordinary draft analysis still validates the resulting changes.
    """
    tracks = {track.track_id: track for track in desired.tracks}
    removed = {track.track_id for track in original.tracks} - tracks.keys()
    if not removed:
        return desired
    removed_pids = {
        track.ipod.db_track_id
        for track in original.tracks
        if track.track_id in removed and track.ipod is not None
    } - {track.ipod.db_track_id for track in desired.tracks if track.ipod is not None}
    previous = {playlist.playlist_id: playlist for playlist in original.playlists}
    playlists: list[Playlist] = []
    for playlist in desired.playlists:
        old = previous.get(playlist.playlist_id)
        if (
            old is None
            or old.kind is not PlaylistKind.GENIUS
            or playlist.kind is not PlaylistKind.GENIUS
        ):
            playlists.append(playlist)
            continue
        entries = tuple(e for e in playlist.entries if e.track_id not in removed)
        retained_entries = tuple(e for e in old.entries if e.track_id in tracks)
        lost_seed = old.genius_seed_persistent_id in removed_pids
        affected = lost_seed or any(e.track_id in removed for e in old.entries)
        if affected and not retained_entries:
            continue
        seed = playlist.genius_seed_persistent_id
        if lost_seed and seed == old.genius_seed_persistent_id:
            first = tracks.get(retained_entries[0].track_id)
            if first is not None and first.ipod is not None:
                seed = first.ipod.db_track_id
        playlists.append(
            replace(playlist, entries=entries, genius_seed_persistent_id=seed)
        )
    return replace(desired, playlists=tuple(playlists))
