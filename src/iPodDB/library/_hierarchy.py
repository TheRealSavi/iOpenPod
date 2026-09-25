"""Pure folder ordering and membership for resolution."""

from collections import defaultdict

from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.playlists import Playlist, PlaylistKind


def folder_hierarchy(
    snapshot: LibrarySnapshot,
) -> tuple[
    list[Playlist], dict[int, tuple[int, ...]], dict[int | None, list[Playlist]]
]:
    children: dict[int | None, list[Playlist]] = defaultdict(list)
    for playlist in snapshot.playlists:
        children[playlist.parent_id].append(playlist)
    ordered: list[Playlist] = []
    pending = list(reversed(children[None]))
    while pending:
        playlist = pending.pop()
        ordered.append(playlist)
        pending.extend(reversed(children[playlist.playlist_id]))
    aggregates: dict[int, tuple[int, ...]] = {}
    for playlist in reversed(ordered):
        aggregates[playlist.playlist_id] = (
            tuple(
                dict.fromkeys(
                    track_id
                    for child in children[playlist.playlist_id]
                    for track_id in aggregates[child.playlist_id]
                )
            )
            if playlist.kind is PlaylistKind.FOLDER
            else playlist.track_ids
        )
    return ordered, aggregates, children
