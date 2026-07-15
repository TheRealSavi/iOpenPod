"""Dropped-file discovery and classification for import workflows."""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DroppedImportFiles:
    """Dropped files grouped by the importer that will handle them."""

    track_paths: tuple[Path, ...] = ()
    photo_imports: tuple[tuple[str, str], ...] = ()
    playlist_paths: tuple[Path, ...] = ()

    @property
    def has_files(self) -> bool:
        return bool(self.track_paths or self.photo_imports or self.playlist_paths)


def is_media_drop_candidate(
    path: Path,
    *,
    include_video: bool = True,
    include_photo: bool = True,
    include_playlist: bool = True,
) -> bool:
    """Return whether a path should activate the media drop overlay."""

    return path.is_dir() or has_supported_import_extension(
        path,
        include_video=include_video,
        include_photo=include_photo,
        include_playlist=include_playlist,
    )


def is_supported_media_file(path: Path, *, include_video: bool = True) -> bool:
    """Return whether a path is a supported media file."""

    from iopenpod.sync._formats import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS

    extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS
    return path.is_file() and path.suffix.lower() in extensions


def has_supported_media_extension(path: Path, *, include_video: bool = True) -> bool:
    """Return whether a path name looks like a supported media file."""

    from iopenpod.sync._formats import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS

    extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS
    return path.suffix.lower() in extensions


def is_supported_photo_file(path: Path) -> bool:
    """Return whether a path is a supported photo import file."""

    from iopenpod.sync._formats import PHOTO_EXTENSIONS

    return path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS


def has_supported_photo_extension(path: Path) -> bool:
    """Return whether a path name looks like a supported photo import file."""

    from iopenpod.sync._formats import PHOTO_EXTENSIONS

    return path.suffix.lower() in PHOTO_EXTENSIONS


def is_supported_playlist_file(path: Path) -> bool:
    """Return whether a path is a supported playlist import file."""

    from iopenpod.sync._formats import PLAYLIST_EXTENSIONS

    return path.is_file() and path.suffix.lower() in PLAYLIST_EXTENSIONS


def has_supported_playlist_extension(path: Path) -> bool:
    """Return whether a path name looks like a supported playlist import file."""

    from iopenpod.sync._formats import PLAYLIST_EXTENSIONS

    return path.suffix.lower() in PLAYLIST_EXTENSIONS


def is_supported_import_file(
    path: Path,
    *,
    include_video: bool = True,
    include_photo: bool = True,
    include_playlist: bool = True,
) -> bool:
    """Return whether a path is any supported drag-and-drop import file."""

    return (
        is_supported_media_file(path, include_video=include_video)
        or (include_photo and is_supported_photo_file(path))
        or (include_playlist and is_supported_playlist_file(path))
    )


def has_supported_import_extension(
    path: Path,
    *,
    include_video: bool = True,
    include_photo: bool = True,
    include_playlist: bool = True,
) -> bool:
    """Return whether a path name looks like any supported import file.

    Drag-enter must be generous: Windows Explorer may present paths before the
    target process can stat them, so acceptance is based on the name. The drop
    scan still validates the file before importing it.
    """

    return (
        has_supported_media_extension(path, include_video=include_video)
        or (include_photo and has_supported_photo_extension(path))
        or (include_playlist and has_supported_playlist_extension(path))
    )


def append_unique_path(paths: list[Path], seen: set[str], path: Path) -> None:
    """Append a path once using the same identity rules as drop discovery."""

    key = _path_key(path)
    if key in seen:
        return
    seen.add(key)
    paths.append(path)


def collect_media_file_paths(
    paths: list[Path],
    *,
    include_video: bool = True,
) -> list[Path]:
    """Expand dropped files/folders into supported media file paths."""

    return list(
        collect_import_file_paths(
            paths,
            include_video=include_video,
            include_photo=False,
            include_playlist=False,
        ).track_paths
    )


def collect_import_file_paths(
    paths: list[Path],
    *,
    include_video: bool = True,
    include_photo: bool = True,
    include_playlist: bool = True,
) -> DroppedImportFiles:
    """Expand dropped files/folders into grouped import file paths."""

    track_paths: list[Path] = []
    photo_imports: list[tuple[str, str]] = []
    playlist_paths: list[Path] = []
    seen_tracks: set[str] = set()
    seen_photos: set[str] = set()
    seen_playlists: set[str] = set()

    def _add_candidate(candidate: Path, album_name: str = "") -> None:
        if is_supported_media_file(candidate, include_video=include_video):
            append_unique_path(track_paths, seen_tracks, candidate)
            return
        if include_photo and is_supported_photo_file(candidate):
            key = _path_key(candidate)
            if key not in seen_photos:
                seen_photos.add(key)
                photo_imports.append((str(candidate), album_name))
            return
        if include_playlist and is_supported_playlist_file(candidate):
            append_unique_path(playlist_paths, seen_playlists, candidate)

    for path in paths:
        if path.is_dir():
            for root, dirs, files in os.walk(path):
                dirs.sort()
                root_path = Path(root)
                try:
                    rel_parent = root_path.relative_to(path)
                except ValueError:
                    rel_parent = Path()
                album_name = rel_parent.as_posix() if rel_parent.parts else ""
                for filename in sorted(files):
                    _add_candidate(root_path / filename, album_name)
        else:
            _add_candidate(path)

    return DroppedImportFiles(
        track_paths=tuple(track_paths),
        photo_imports=tuple(photo_imports),
        playlist_paths=tuple(playlist_paths),
    )


def build_dropped_playlist_imports(
    playlist_paths: Iterable[Path],
    *,
    include_video: bool = True,
) -> tuple[list[Path], list[dict]]:
    """Parse dropped playlist files into media paths and pending playlists."""

    from iopenpod.sync.playlist_parser import PlaylistPathResolver, parse_playlist

    media_paths: list[Path] = []
    seen_media: set[str] = set()
    playlists: list[dict] = []
    resolver = PlaylistPathResolver()
    for playlist_path in playlist_paths:
        try:
            raw_paths, playlist_name = parse_playlist(playlist_path)
        except Exception as exc:
            logger.warning("Failed to parse dropped playlist %s: %s", playlist_path, exc)
            continue
        items: list[dict] = []
        for raw_path in raw_paths:
            resolved_path = resolver.resolve_existing_path(raw_path)
            if resolved_path is None:
                continue
            path = Path(resolved_path)
            if not is_supported_media_file(path, include_video=include_video):
                continue
            append_unique_path(media_paths, seen_media, path)
            items.append({"source_path": str(path)})
        if items:
            playlists.append(
                {
                    "Title": playlist_name,
                    "playlist_id": random.getrandbits(64),
                    "_isNew": True,
                    "_source": "regular",
                    "items": items,
                }
            )
    return media_paths, playlists


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path))
