"""Deterministic planning stages used by the sync diff engine."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .path_identity import stable_path_key
from .pc_library import PCTrack
from .sync_playlist_files import (
    SyncPlaylistDiscovery,
    discover_sync_playlist_files,
    normalize_sync_playlist_path,
)

logger = logging.getLogger(__name__)

PlanningProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class SourceLibrary(Protocol):
    """Scanner surface needed by source planning stages."""

    root_entries: Any

    def scan(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
        include_video: bool = True,
        max_workers: int | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Iterable[Any]:
        ...

    def _read_track(
        self,
        file_path: Path,
        library_root: Path | None = None,
    ) -> Any | None:
        ...


@dataclass(frozen=True, slots=True)
class SourceLibraryScan:
    """Output from source-library scanning stages."""

    pc_tracks: tuple[Any, ...]
    playlist_discovery: SyncPlaylistDiscovery | None = None
    selected_playlist_source_keys: frozenset[str] | None = None
    playlist_extra_source_keys: frozenset[str] = frozenset()
    cancelled: bool = False


def scan_source_libraries(
    pc_library: SourceLibrary,
    *,
    supports_video: bool,
    supports_podcast: bool,
    sync_workers: int,
    allowed_paths: frozenset[str] | None,
    selected_playlist_paths: frozenset[str] | None,
    progress_callback: PlanningProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> SourceLibraryScan:
    """Scan PC media and playlist-file references for planning."""

    if _is_cancelled(is_cancelled):
        return SourceLibraryScan(pc_tracks=(), cancelled=True)

    if progress_callback:
        progress_callback("scan_pc", 0, 0, "Scanning media folders")

    scan_workers = min(sync_workers or (os.cpu_count() or 4), 8)

    def _scan_progress(current: int, total: int, filename: str) -> None:
        if progress_callback:
            progress_callback("scan_pc", current, total, filename)

    pc_tracks = list(
        pc_library.scan(
            progress_callback=_scan_progress,
            include_video=supports_video,
            max_workers=scan_workers,
            is_cancelled=is_cancelled,
        )
    )

    if _is_cancelled(is_cancelled):
        return SourceLibraryScan(pc_tracks=tuple(pc_tracks), cancelled=True)

    playlist_discovery = None
    selected_playlist_source_keys: frozenset[str] | None = None
    playlist_extra_source_keys: frozenset[str] = frozenset()
    if allowed_paths is None or selected_playlist_paths is not None:
        (
            playlist_discovery,
            selected_playlist_source_keys,
            playlist_extra_source_keys,
        ) = _scan_playlist_references(
            pc_library,
            pc_tracks,
            supports_video=supports_video,
            selected_playlist_paths=selected_playlist_paths,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )
        if _is_cancelled(is_cancelled):
            return SourceLibraryScan(
                pc_tracks=tuple(pc_tracks),
                playlist_discovery=playlist_discovery,
                selected_playlist_source_keys=selected_playlist_source_keys,
                playlist_extra_source_keys=playlist_extra_source_keys,
                cancelled=True,
            )

    if allowed_paths is not None:
        allowed_path_keys = {stable_path_key(path) for path in allowed_paths}
        if playlist_discovery is not None and selected_playlist_source_keys is not None:
            for playlist in playlist_discovery.playlists:
                if (
                    normalize_sync_playlist_path(playlist.source_path)
                    not in selected_playlist_source_keys
                ):
                    continue
                allowed_path_keys.update(
                    normalize_sync_playlist_path(path)
                    for path in playlist.media_paths
                )
        pc_tracks = [
            track for track in pc_tracks
            if stable_path_key(track.path) in allowed_path_keys
        ]

    if not supports_podcast:
        pc_tracks = [track for track in pc_tracks if not track.is_podcast]

    return SourceLibraryScan(
        pc_tracks=tuple(pc_tracks),
        playlist_discovery=playlist_discovery,
        selected_playlist_source_keys=selected_playlist_source_keys,
        playlist_extra_source_keys=playlist_extra_source_keys,
    )


def _scan_playlist_references(
    pc_library: SourceLibrary,
    pc_tracks: list[PCTrack],
    *,
    supports_video: bool,
    selected_playlist_paths: frozenset[str] | None,
    progress_callback: PlanningProgressCallback | None,
    is_cancelled: CancelCallback | None,
) -> tuple[SyncPlaylistDiscovery | None, frozenset[str] | None, frozenset[str]]:
    try:
        if progress_callback:
            progress_callback("scan_playlists", 0, 0, "Scanning playlist files")

        playlist_discovery = discover_sync_playlist_files(
            pc_library.root_entries,
            include_video=supports_video,
        )
        selected_playlist_source_keys = None
        if selected_playlist_paths is not None:
            selected_playlist_source_keys = frozenset(
                normalize_sync_playlist_path(path)
                for path in selected_playlist_paths
            )

        existing_source_keys = {
            normalize_sync_playlist_path(track.path)
            for track in pc_tracks
        }
        playlist_media_paths: list[str] = []
        for playlist in playlist_discovery.playlists:
            if (
                selected_playlist_source_keys is not None
                and normalize_sync_playlist_path(playlist.source_path)
                not in selected_playlist_source_keys
            ):
                continue
            playlist_media_paths.extend(playlist.media_paths)

        extra_media_paths = [
            path
            for path in playlist_media_paths
            if normalize_sync_playlist_path(path) not in existing_source_keys
        ]
        total_extra = len(extra_media_paths)
        playlist_extra_source_keys: set[str] = set()
        for index, raw_path in enumerate(extra_media_paths, start=1):
            if _is_cancelled(is_cancelled):
                break
            path = Path(raw_path)
            if progress_callback:
                progress_callback(
                    "scan_playlists",
                    index,
                    total_extra,
                    f"Resolving playlist track: {path.name}",
                )
            try:
                track = pc_library._read_track(path)
            except Exception as exc:
                logger.warning(
                    "Failed to read playlist-referenced track %s: %s",
                    path,
                    exc,
                )
                continue
            if track is None:
                continue
            source_key = normalize_sync_playlist_path(track.path)
            pc_tracks.append(track)
            existing_source_keys.add(source_key)
            playlist_extra_source_keys.add(source_key)

        return playlist_discovery, selected_playlist_source_keys, frozenset(playlist_extra_source_keys)
    except Exception as exc:
        logger.warning("Playlist-file sync planning scan failed: %s", exc)
        return None, None, frozenset()


def _is_cancelled(is_cancelled: CancelCallback | None) -> bool:
    return bool(is_cancelled and is_cancelled())
