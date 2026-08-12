"""Read-only smart-playlist preview computation.

The GUI submits this work to the shared thread pool.  This module deliberately
depends on only the cache's read surface: previewing must never update the
in-memory user-playlist store or write an iTunesDB.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from iopenpod.itunesdb_shared.device_time import DeviceTimeContext
from iopenpod.sync._playlist_builder import sort_tracks_by_order
from iopenpod.sync.spl_evaluator import spl_update_from_parsed


class SmartPlaylistPreviewSource(Protocol):
    """The read-only cache surface needed by a preview worker."""

    def get_tracks(self) -> list[dict]: ...

    def get_playlists(self) -> list[dict]: ...

    def get_data(self) -> dict | None: ...


@dataclass(frozen=True, slots=True)
class SmartPlaylistPreviewRequest:
    """One immutable-in-practice editor state submitted for evaluation."""

    generation: int
    preferences: dict
    rules: dict
    sort_order: int = 1


@dataclass(frozen=True, slots=True)
class SmartPlaylistPreviewResult:
    """Tracks ready for incremental presentation by the GUI."""

    generation: int
    tracks: list[dict]


def _playlist_membership_lookup(playlists: list[dict]) -> dict[int, set[int]]:
    lookup: dict[int, set[int]] = {}
    for playlist in playlists:
        playlist_id = playlist.get("playlist_id", 0)
        if not isinstance(playlist_id, int):
            continue
        items = playlist.get("items", [])
        if not isinstance(items, list):
            continue
        lookup[playlist_id] = {track_id for item in items if isinstance(item, dict) and isinstance((track_id := item.get("track_id")), int)}
    return lookup


def compute_smart_playlist_preview(
    request: SmartPlaylistPreviewRequest,
    source: SmartPlaylistPreviewSource,
    is_cancelled: Callable[[], bool],
) -> SmartPlaylistPreviewResult:
    """Compute a transient preview from cache reads without mutating either input."""

    if is_cancelled():
        return SmartPlaylistPreviewResult(request.generation, [])

    # These cache reads and all O(n) work happen on the worker thread.  The
    # cache returns shallow snapshots; the evaluator only reads track rows.
    tracks = source.get_tracks()
    if is_cancelled():
        return SmartPlaylistPreviewResult(request.generation, [])

    playlists = source.get_playlists()
    playlist_lookup = _playlist_membership_lookup(playlists)
    if is_cancelled():
        return SmartPlaylistPreviewResult(request.generation, [])

    time_context: DeviceTimeContext | None = None
    data = source.get_data()
    candidate = data.get("device_time_context") if isinstance(data, dict) else None
    if isinstance(candidate, DeviceTimeContext):
        time_context = candidate

    track_ids = spl_update_from_parsed(
        request.preferences,
        request.rules,
        tracks,
        playlist_lookup,
        time_context,
        is_cancelled=is_cancelled,
    )
    if is_cancelled():
        return SmartPlaylistPreviewResult(request.generation, [])

    track_index = {track_id: track for track in tracks if isinstance((track_id := track.get("track_id")), int)}
    matched_tracks = [track_index[track_id] for track_id in track_ids if track_id in track_index]
    matched_tracks = sort_tracks_by_order(matched_tracks, request.sort_order)
    if is_cancelled():
        return SmartPlaylistPreviewResult(request.generation, [])

    return SmartPlaylistPreviewResult(request.generation, matched_tracks)
