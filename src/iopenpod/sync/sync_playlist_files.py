"""Planning helpers for playlist files discovered during media-folder sync."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from iopenpod.infrastructure.media_folders import (
    MEDIA_TYPE_PLAYLISTS,
    MediaFolderEntry,
)

from ._formats import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from .path_identity import coerce_int, stable_path_key
from .playlist_parser import PlaylistPathResolver, parse_playlist

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

    return stable_path_key(path)


def sync_playlist_file_id(path: str | Path) -> int:
    """Return a deterministic managed playlist id for a source playlist path."""

    normalized = normalize_sync_playlist_path(path).encode("utf-8", errors="surrogatepass")
    suffix = int.from_bytes(hashlib.blake2b(normalized, digest_size=5).digest(), "big")
    return (_MANAGED_PLAYLIST_ID_PREFIX << _MANAGED_PLAYLIST_ID_SHIFT) | suffix


def is_managed_sync_playlist_id(value: object) -> bool:
    playlist_id = coerce_int(value)
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
    resolver = PlaylistPathResolver()
    normalized_cache: dict[str, str] = {}
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
            if not _is_supported_media_path(Path(raw_path), include_video=include_video):
                skipped += 1
                continue

            resolved = resolver.resolve_existing_path(raw_path)
            if resolved is None:
                skipped += 1
                continue
            path = Path(resolved)

            normalized = _cached_normalize(path, normalized_cache)
            items.append({"source_path": normalized})
            playlist_media_paths.append(normalized)
            if normalized not in seen_media:
                seen_media.add(normalized)
                media_paths.append(normalized)

        playlists.append(
            SyncPlaylistFile(
                source_path=_cached_normalize(playlist_path, normalized_cache),
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


def _cached_normalize(path: str | Path, cache: dict[str, str]) -> str:
    key = os.fspath(path)
    cached = cache.get(key)
    if cached is not None:
        return cached
    normalized = normalize_sync_playlist_path(path)
    cache[key] = normalized
    return normalized
