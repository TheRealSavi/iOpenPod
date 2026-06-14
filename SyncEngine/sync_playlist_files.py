"""Planning helpers for playlist files discovered during media-folder sync."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from infrastructure.media_folders import (
    MEDIA_TYPE_PLAYLISTS,
    MediaFolderEntry,
)

from ._formats import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from .playlist_parser import parse_playlist, resolve_existing_playlist_path

logger = logging.getLogger(__name__)

SUPPORTED_PLAYLIST_EXTENSIONS = frozenset({".m3u", ".m3u8", ".pls", ".xspf"})
SYNC_PLAYLIST_SOURCE = "sync_playlist_file"

_MANAGED_PLAYLIST_ID_PREFIX = 0x494F50
_MANAGED_PLAYLIST_ID_SHIFT = 40


@dataclass(frozen=True)
class SyncPlaylistFile:
    """A parsed source playlist file ready for sync-plan comparison."""

    source_path: str
    playlist_id: int
    title: str
    items: tuple[dict[str, str], ...]
    media_paths: tuple[str, ...]
    total_entries: int
    skipped_entries: int


@dataclass(frozen=True)
class SyncPlaylistDiscovery:
    """Playlist-file scan output."""

    playlists: tuple[SyncPlaylistFile, ...] = ()
    media_paths: tuple[str, ...] = ()
    source_playlist_ids: tuple[int, ...] = ()


def normalize_sync_playlist_path(path: str | Path) -> str:
    """Return the stable absolute path key used for managed playlist identity."""

    try:
        return os.path.normcase(str(Path(path).expanduser().resolve()))
    except OSError:
        return os.path.normcase(str(Path(path).expanduser().absolute()))


def sync_playlist_file_id(path: str | Path) -> int:
    """Return a deterministic managed playlist id for a source playlist path."""

    normalized = normalize_sync_playlist_path(path).encode("utf-8", errors="surrogatepass")
    suffix = int.from_bytes(hashlib.blake2b(normalized, digest_size=5).digest(), "big")
    return (_MANAGED_PLAYLIST_ID_PREFIX << _MANAGED_PLAYLIST_ID_SHIFT) | suffix


def is_managed_sync_playlist_id(value: object) -> bool:
    playlist_id = _coerce_int(value)
    return (playlist_id >> _MANAGED_PLAYLIST_ID_SHIFT) == _MANAGED_PLAYLIST_ID_PREFIX


def discover_sync_playlist_files(
    root_entries: Sequence[MediaFolderEntry],
    *,
    include_video: bool,
) -> SyncPlaylistDiscovery:
    """Scan media-folder roots for supported playlist files and parse them."""

    playlist_paths = _scan_playlist_files(root_entries, include_video=include_video)
    playlists: list[SyncPlaylistFile] = []
    media_paths: list[str] = []
    seen_media: set[str] = set()
    source_playlist_ids = tuple(sync_playlist_file_id(path) for path in playlist_paths)

    for playlist_path in playlist_paths:
        try:
            raw_paths, playlist_name = parse_playlist(playlist_path)
        except Exception as exc:
            logger.warning("Failed to parse sync playlist %s: %s", playlist_path, exc)
            continue

        items: list[dict[str, str]] = []
        playlist_media_paths: list[str] = []
        skipped = 0
        for raw_path in raw_paths:
            resolved = resolve_existing_playlist_path(raw_path)
            if resolved is None:
                skipped += 1
                continue
            path = Path(resolved)
            if not _is_supported_media_path(path, include_video=include_video):
                skipped += 1
                continue

            normalized = normalize_sync_playlist_path(path)
            items.append({"source_path": normalized})
            playlist_media_paths.append(normalized)
            if normalized not in seen_media:
                seen_media.add(normalized)
                media_paths.append(normalized)

        playlists.append(
            SyncPlaylistFile(
                source_path=normalize_sync_playlist_path(playlist_path),
                playlist_id=sync_playlist_file_id(playlist_path),
                title=playlist_name,
                items=tuple(items),
                media_paths=tuple(playlist_media_paths),
                total_entries=len(raw_paths),
                skipped_entries=skipped,
            )
        )

    return SyncPlaylistDiscovery(
        playlists=tuple(playlists),
        media_paths=tuple(media_paths),
        source_playlist_ids=source_playlist_ids,
    )


def build_sync_playlist_changes(
    discovery: SyncPlaylistDiscovery,
    existing_playlists: Iterable[dict],
    ipod_tracks: Iterable[dict],
    *,
    source_path_to_db_track_id: dict[str, int],
    pending_add_source_paths: set[str],
    valid_source_paths: set[str],
    source_path_aliases: dict[str, str] | None = None,
    selected_playlist_source_paths: set[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return playlist add/edit/remove payloads for discovered sync playlists."""

    aliases = source_path_aliases or {}
    selected_playlist_keys = selected_playlist_source_paths
    old_tid_to_db_track_id = _old_tid_to_db_track_id(ipod_tracks)
    existing_by_id: dict[int, dict] = {}
    managed_existing: dict[int, dict] = {}
    for playlist in existing_playlists:
        if playlist.get("master_flag"):
            continue
        playlist_id = _coerce_int(playlist.get("playlist_id"))
        if not playlist_id:
            continue
        existing_by_id.setdefault(playlist_id, playlist)
        if is_managed_sync_playlist_id(playlist_id):
            managed_existing.setdefault(playlist_id, playlist)

    current_ids = set(discovery.source_playlist_ids)
    to_add: list[dict] = []
    to_edit: list[dict] = []

    for playlist in discovery.playlists:
        if (
            selected_playlist_keys is not None
            and normalize_sync_playlist_path(playlist.source_path) not in selected_playlist_keys
        ):
            continue
        payload = _playlist_payload(playlist, valid_source_paths, aliases)
        existing = existing_by_id.get(playlist.playlist_id)
        if existing is None:
            to_add.append(payload)
            continue

        payload["_isNew"] = False
        if _playlist_needs_update(
            existing,
            payload,
            old_tid_to_db_track_id,
            source_path_to_db_track_id,
            pending_add_source_paths,
        ):
            to_edit.append(payload)

    to_remove = [
        {
            **dict(playlist),
            "_source": SYNC_PLAYLIST_SOURCE,
            "_sync_playlist_deleted": True,
        }
        for playlist_id, playlist in sorted(managed_existing.items())
        if playlist_id not in current_ids
    ]

    return to_add, to_edit, to_remove


def _scan_playlist_files(
    root_entries: Sequence[MediaFolderEntry],
    *,
    include_video: bool,
) -> tuple[Path, ...]:
    paths: list[Path] = []
    seen: set[str] = set()
    for entry in root_entries:
        if not _entry_allows_playlist_scan(entry):
            continue
        root_path = Path(entry.directory)
        for root, filename in _iter_root_files(root_path, recurse=entry.recurse):
            if Path(filename).suffix.lower() not in SUPPORTED_PLAYLIST_EXTENSIONS:
                continue
            path = root / filename
            key = normalize_sync_playlist_path(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return tuple(sorted(paths, key=lambda path: normalize_sync_playlist_path(path)))


def _entry_allows_playlist_scan(entry: MediaFolderEntry) -> bool:
    return MEDIA_TYPE_PLAYLISTS in set(entry.media_types)


def _iter_root_files(root_path: Path, *, recurse: bool):
    if recurse:
        for root, dirs, files in os.walk(root_path):
            dirs[:] = [dirname for dirname in dirs if dirname != ".AppleDouble"]
            for filename in files:
                if _should_skip_library_file(filename):
                    continue
                yield Path(root), filename
        return

    for child in root_path.iterdir():
        if child.is_file() and not _should_skip_library_file(child.name):
            yield root_path, child.name


def _should_skip_library_file(filename: str) -> bool:
    return filename.startswith("._") or filename == ".DS_Store"


def _is_supported_media_path(path: Path, *, include_video: bool) -> bool:
    ext = path.suffix.lower()
    return ext in AUDIO_EXTENSIONS or (include_video and ext in VIDEO_EXTENSIONS)


def _playlist_payload(
    playlist: SyncPlaylistFile,
    valid_source_paths: set[str],
    source_path_aliases: dict[str, str],
) -> dict:
    items: list[dict[str, str]] = []
    for item in playlist.items:
        source_path = normalize_sync_playlist_path(item["source_path"])
        source_path = source_path_aliases.get(source_path, source_path)
        if source_path in valid_source_paths:
            items.append({"source_path": source_path})
    skipped = playlist.skipped_entries + (len(playlist.items) - len(items))
    return {
        "Title": playlist.title,
        "playlist_id": playlist.playlist_id,
        "_isNew": True,
        "_source": SYNC_PLAYLIST_SOURCE,
        "_mhsd_dataset_type": 2,
        "_mhsd_result_key": "mhlp",
        "_sync_playlist_path": playlist.source_path,
        "_sync_playlist_total_entries": playlist.total_entries,
        "_sync_playlist_skipped_count": skipped,
        "items": items,
        "mhip_child_count": len(items),
    }


def _playlist_needs_update(
    existing: dict,
    desired: dict,
    old_tid_to_db_track_id: dict[int, int],
    source_path_to_db_track_id: dict[str, int],
    pending_add_source_paths: set[str],
) -> bool:
    if existing.get("Title") != desired.get("Title"):
        return True

    desired_ids: list[int] = []
    has_pending_add = False
    for item in desired.get("items", []):
        source_path = item.get("source_path") or item.get("_source_path")
        source_key = normalize_sync_playlist_path(source_path or "")
        db_track_id = source_path_to_db_track_id.get(source_key)
        if db_track_id:
            desired_ids.append(db_track_id)
        elif source_key in pending_add_source_paths:
            has_pending_add = True
        else:
            return True

    if has_pending_add:
        return True

    existing_ids = _playlist_db_track_ids(existing.get("items", []), old_tid_to_db_track_id)
    return existing_ids != desired_ids


def _playlist_db_track_ids(
    items: Iterable[dict],
    old_tid_to_db_track_id: dict[int, int],
) -> list[int]:
    result: list[int] = []
    for item in items:
        db_track_id = _coerce_int(item.get("db_track_id", item.get("db_id", 0)))
        if not db_track_id:
            db_track_id = old_tid_to_db_track_id.get(_coerce_int(item.get("track_id")), 0)
        if db_track_id:
            result.append(db_track_id)
    return result


def _old_tid_to_db_track_id(ipod_tracks: Iterable[dict]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in ipod_tracks:
        track_id = _coerce_int(track.get("track_id"))
        db_track_id = _coerce_int(track.get("db_track_id", track.get("db_id", 0)))
        if track_id and db_track_id:
            result[track_id] = db_track_id
    return result


def _coerce_int(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
