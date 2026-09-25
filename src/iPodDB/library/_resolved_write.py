"""Private immutable execution decisions; no caller-owned commands or Chunk bindings."""

from dataclasses import dataclass

from iPodDB.library._browse_index import BrowseIndex
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import LibraryWritePlan


@dataclass(frozen=True, slots=True)
class FolderWrite:
    playlist_id: int
    track_ids: tuple[int, ...]
    child_ids: tuple[int, ...]
    previous_child_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ResolvedWrite:
    plan: LibraryWritePlan
    original: LibrarySnapshot
    desired: LibrarySnapshot
    affected_datasets: frozenset[int]
    structural_tracks: bool
    changed_playlists: frozenset[int]
    generated_podcasts: frozenset[int]
    podcast_playlists: frozenset[int]
    playlist_order: tuple[int, ...]
    topology_changed: bool
    folders: tuple[FolderWrite, ...]
    indexes: tuple[BrowseIndex, ...]
    track_ids: tuple[tuple[int, int], ...]
    playlist_ids: tuple[tuple[int, int], ...]
    persistent_ids: tuple[tuple[int, int], ...]
    artwork_tracks: tuple[int, ...] = ()
    deleted_tracks: frozenset[int] = frozenset()
