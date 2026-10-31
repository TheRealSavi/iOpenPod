"""Resolve Phase's ID-first, exact-name fallback Playlist selection."""

from dataclasses import replace

from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.playlists import PlaylistKind


def resolve_phase_playlist(
    snapshot: LibrarySnapshot, playlist_id: int | None
) -> LibrarySnapshot:
    candidates = tuple(
        p
        for p in snapshot.playlists
        if not p.system_managed
        and p.kind in (PlaylistKind.PLAYLIST, PlaylistKind.SMART)
    )
    selected = next(
        (p for p in candidates if playlist_id and p.playlist_id == playlist_id), None
    )
    if selected is None:
        selected = next((p for p in candidates if p.name == "Phase"), None)
    return replace(
        snapshot,
        playlists=tuple(
            replace(
                p,
                is_phase=selected is not None and p.playlist_id == selected.playlist_id,
            )
            for p in snapshot.playlists
        ),
    )
