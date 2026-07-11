"""Normalized internal contexts for SyncEngine operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iopenpod.infrastructure.media_folders import normalize_media_folder_entries
from iopenpod.sync.path_identity import coerce_int, stable_path_key

from .models import EngineRequest


@dataclass(frozen=True, slots=True)
class EnginePlanContext:
    """Normalized planning inputs derived from an :class:`EngineRequest`.

    This is the boundary between app-facing request objects and planning
    internals.  Anything ambiguous or path-like should be canonicalized here
    before lower stages use it.
    """

    request: EngineRequest
    ipod_path: str
    ipod_root: Path
    pc_folders: tuple[Any, ...]
    pc_folder_keys: tuple[str, ...]
    ipod_tracks: tuple[dict, ...]
    existing_playlists: tuple[dict, ...]
    ipod_by_db_track_id: Mapping[int, dict]
    old_track_id_to_db_track_id: Mapping[int, int]
    playlist_by_id: Mapping[int, dict]
    track_edits: Mapping[int, dict[str, tuple]]
    allowed_path_keys: frozenset[str] | None
    selected_playlist_source_keys: frozenset[str] | None
    photo_sync_settings: dict[str, bool]
    mapping: Any = None

    @classmethod
    def from_request(cls, request: EngineRequest) -> EnginePlanContext:
        ipod_path = str(request.ipod_path or "")
        pc_folders = tuple(_valid_pc_folder_inputs(request.pc_folders))
        normalized_folder_entries = tuple(normalize_media_folder_entries(pc_folders))
        ipod_tracks = tuple(request.ipod_tracks)
        existing_playlists = tuple(request.existing_playlists)

        return cls(
            request=request,
            ipod_path=ipod_path,
            ipod_root=Path(ipod_path) if ipod_path else Path(),
            pc_folders=pc_folders,
            pc_folder_keys=tuple(
                stable_path_key(entry.directory)
                for entry in normalized_folder_entries
            ),
            ipod_tracks=ipod_tracks,
            existing_playlists=existing_playlists,
            ipod_by_db_track_id=_ipod_by_db_track_id(ipod_tracks),
            old_track_id_to_db_track_id=_old_track_id_to_db_track_id(ipod_tracks),
            playlist_by_id=_playlist_by_id(existing_playlists),
            track_edits=dict(request.track_edits or {}),
            allowed_path_keys=_canonical_path_set(request.options.allowed_paths),
            selected_playlist_source_keys=_canonical_path_set(
                request.options.selected_playlist_paths
            ),
            photo_sync_settings=dict(request.options.photo_sync_settings or {}),
            mapping=request.mapping,
        )


def _canonical_path_set(paths: frozenset[str] | None) -> frozenset[str] | None:
    if paths is None:
        return None
    return frozenset(stable_path_key(path) for path in paths)


def _valid_pc_folder_inputs(values: tuple[Any, ...]) -> tuple[Any, ...]:
    result: list[Any] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        result.append(value)
    return tuple(result)


def _ipod_by_db_track_id(tracks: tuple[dict, ...]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for track in tracks:
        db_track_id = coerce_int(track.get("db_track_id", track.get("db_id", 0)))
        if db_track_id:
            result[db_track_id] = track
    return result


def _old_track_id_to_db_track_id(tracks: tuple[dict, ...]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in tracks:
        track_id = coerce_int(track.get("track_id"))
        db_track_id = coerce_int(track.get("db_track_id", track.get("db_id", 0)))
        if track_id and db_track_id:
            result[track_id] = db_track_id
    return result


def _playlist_by_id(playlists: tuple[dict, ...]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for playlist in playlists:
        playlist_id = coerce_int(playlist.get("playlist_id"))
        if playlist_id:
            result.setdefault(playlist_id, playlist)
    return result
