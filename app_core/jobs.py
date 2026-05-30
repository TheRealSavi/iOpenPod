"""Operational background jobs owned by the application core layer."""

from __future__ import annotations

import copy
import logging
import os
import random
import re
import shutil
import tempfile
import threading
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QThread, pyqtSignal

from infrastructure.media_folders import media_folder_paths

from .sync_options import build_transcode_options

if TYPE_CHECKING:
    from infrastructure.settings_schema import AppSettings

    from .services import (
        DeviceCapabilitySnapshot,
        DeviceIdentitySnapshot,
        LibraryCacheLike,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncToolAvailability:
    """Availability of external tools required or recommended before sync."""

    missing_ffmpeg: bool
    missing_fpcalc: bool
    can_download: bool

    @property
    def has_missing(self) -> bool:
        return self.missing_ffmpeg or self.missing_fpcalc

    @property
    def can_continue_without_download(self) -> bool:
        return not self.missing_fpcalc

    @property
    def tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.missing_fpcalc:
            names.append("fpcalc (Chromaprint)")
        if self.missing_ffmpeg:
            names.append("FFmpeg")
        return tuple(names)

    @property
    def tool_list(self) -> str:
        return " and ".join(self.tool_names)

    @property
    def install_help_text(self) -> str:
        lines = []
        if self.missing_fpcalc:
            lines.append(
                "fpcalc is required for sync.\n"
                "Install from: https://acoustid.org/chromaprint"
            )
        if self.missing_ffmpeg:
            lines.append(
                "FFmpeg is needed for transcoding.\n"
                "Install from: https://ffmpeg.org"
            )
        lines.append("You can also set custom paths in\nSettings -> External Tools.")
        return "\n\n".join(lines)


def check_sync_tool_availability(settings: AppSettings) -> SyncToolAvailability:
    """Return external tool availability for a full PC sync."""

    from SyncEngine.audio_fingerprint import is_fpcalc_available
    from SyncEngine.dependency_manager import is_platform_supported
    from SyncEngine.transcoder import is_ffmpeg_available

    return SyncToolAvailability(
        missing_ffmpeg=not is_ffmpeg_available(settings.ffmpeg_path),
        missing_fpcalc=not is_fpcalc_available(settings.fpcalc_path),
        can_download=is_platform_supported(),
    )


class ToolDownloadWorker(QThread):
    """Download bundled external sync tools outside the GUI thread."""

    completed = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, *, need_ffmpeg: bool, need_fpcalc: bool):
        super().__init__()
        self._need_ffmpeg = need_ffmpeg
        self._need_fpcalc = need_fpcalc

    def run(self) -> None:
        try:
            from SyncEngine.dependency_manager import download_ffmpeg, download_fpcalc

            if self._need_fpcalc:
                download_fpcalc()
            if self._need_ffmpeg:
                download_ffmpeg()
            self.completed.emit()
        except Exception as exc:
            logger.exception("Tool download failed")
            self.error.emit(str(exc))


@dataclass(frozen=True)
class AlbumConversionRequest:
    """Typed request for converting one iPod album into a chaptered track."""

    album_item: dict
    album_tracks: list[dict]
    pc_folders: tuple[Any, ...]
    ipod_path: str
    settings: AppSettings
    artwork_bytes: bytes | None = None


@dataclass(frozen=True)
class AlbumConversionResult:
    """Result returned after preparing a chaptered album sync plan."""

    plan: Any
    output_path: str
    warnings: tuple[str, ...] = ()


class AlbumConversionWorker(QThread):
    """Build a chaptered album file and return a normal sync plan."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, request: AlbumConversionRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            from SyncEngine.album_chapters import (
                convert_album_to_chaptered_track,
                resolve_album_sources,
            )
            from SyncEngine.fingerprint_diff_engine import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from SyncEngine.mapping import MappingManager

            request = self._request
            if len(request.album_tracks) < 2:
                raise ValueError("Choose an album with at least two tracks.")

            self.progress.emit(
                "album_conversion",
                0,
                len(request.album_tracks),
                "Resolving album source files...",
            )
            mapping = MappingManager(request.ipod_path).load()
            sources, source_warnings = resolve_album_sources(
                request.album_tracks,
                pc_folders=request.pc_folders,
                ipod_path=request.ipod_path,
                mapping=mapping,
                fpcalc_path=getattr(request.settings, "fpcalc_path", ""),
            )
            if self.isInterruptionRequested():
                return

            self.progress.emit(
                "album_conversion",
                1,
                3,
                "Encoding chaptered album...",
            )
            converted = convert_album_to_chaptered_track(
                album_item=request.album_item,
                tracks=request.album_tracks,
                sources=sources,
                output_dir=self._output_dir(request.settings),
                settings=request.settings,
                artwork_bytes=request.artwork_bytes,
            )
            if self.isInterruptionRequested():
                return

            group_id = f"album-{random.getrandbits(64):016x}"
            output_size = converted.output_path.stat().st_size
            album_title = (
                request.album_item.get("album")
                or request.album_item.get("title")
                or converted.pc_track.title
            )
            add_item = SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                fingerprint=None,
                pc_track=converted.pc_track,
                estimated_size=output_size,
                description=f"Chaptered album: {album_title}",
                conversion_group_id=group_id,
                conversion_group_add_count=1,
                conversion_source_fingerprints=converted.source_fingerprints,
                conversion_source_path_hints=converted.source_path_hints,
            )

            remove_items = []
            bytes_to_remove = 0
            for track, source in zip(request.album_tracks, sources, strict=False):
                db_track_id = track.get("db_track_id", track.get("db_id"))
                title = track.get("Title", "Unknown")
                artist = track.get("Artist", "")
                size = int(track.get("size", track.get("Size", 0)) or 0)
                remove_items.append(
                    SyncItem(
                        action=SyncAction.REMOVE_FROM_IPOD,
                        fingerprint=source.fingerprint,
                        db_track_id=db_track_id,
                        ipod_track=track,
                        description=(
                            f"Replace with chapter: {artist} - {title}"
                            if artist
                            else f"Replace with chapter: {title}"
                        ),
                        conversion_group_id=group_id,
                        defer_removal_until_after_add=True,
                    )
                )
                bytes_to_remove += size

            plan = SyncPlan(
                to_add=[add_item],
                to_remove=remove_items,
                storage=StorageSummary(
                    bytes_to_add=output_size,
                    bytes_to_remove=bytes_to_remove,
                ),
                removals_pre_checked=True,
                mapping=mapping,
            )

            self.progress.emit(
                "album_conversion",
                3,
                3,
                "Chaptered album is ready for review.",
            )
            self.finished.emit(
                AlbumConversionResult(
                    plan=plan,
                    output_path=str(converted.output_path),
                    warnings=tuple(source_warnings),
                )
            )
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("AlbumConversionWorker failed")
            self.error.emit(str(exc))

    @staticmethod
    def _output_dir(settings: AppSettings) -> Path:
        base = (
            Path(settings.transcode_cache_dir)
            if getattr(settings, "transcode_cache_dir", "")
            else Path(getattr(settings, "settings_dir", "") or tempfile.gettempdir())
        )
        return base / "album-conversions"


@dataclass(frozen=True)
class ChapterSplitRequest:
    """Typed request for splitting one chaptered iPod track."""

    track: dict
    pc_folders: tuple[Any, ...]
    ipod_path: str
    settings: AppSettings
    artwork_bytes: bytes | None = None


@dataclass(frozen=True)
class ChapterSplitResult:
    """Result returned after preparing a chapter-split sync plan."""

    plan: Any
    output_paths: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class ChapterSplitWorker(QThread):
    """Build individual chapter files and return a normal sync plan."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, request: ChapterSplitRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            from SyncEngine.album_chapters import (
                build_chapter_split_segments,
                resolve_track_source,
                split_track_into_chapter_tracks,
            )
            from SyncEngine.fingerprint_diff_engine import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from SyncEngine.mapping import MappingManager

            request = self._request
            segments = build_chapter_split_segments(request.track)
            self.progress.emit(
                "chapter_split",
                0,
                len(segments),
                "Resolving chaptered track source...",
            )
            mapping = MappingManager(request.ipod_path).load()
            source, source_warnings = resolve_track_source(
                request.track,
                pc_folders=request.pc_folders,
                ipod_path=request.ipod_path,
                mapping=mapping,
                fpcalc_path=getattr(request.settings, "fpcalc_path", ""),
            )
            if self.isInterruptionRequested():
                return

            self.progress.emit(
                "chapter_split",
                1,
                len(segments),
                "Splitting chapters into tracks...",
            )
            split = split_track_into_chapter_tracks(
                track=request.track,
                source=source,
                output_dir=self._output_dir(request.settings),
                settings=request.settings,
                artwork_bytes=request.artwork_bytes,
            )
            if self.isInterruptionRequested():
                return

            group_id = f"chapter-split-{random.getrandbits(64):016x}"
            add_items: list[SyncItem] = []
            bytes_to_add = 0
            for pc_track, output_path in zip(split.pc_tracks, split.output_paths, strict=False):
                output_size = output_path.stat().st_size
                bytes_to_add += output_size
                add_items.append(
                    SyncItem(
                        action=SyncAction.ADD_TO_IPOD,
                        fingerprint=None,
                        pc_track=pc_track,
                        estimated_size=output_size,
                        description=f"Split chapter: {pc_track.title}",
                        conversion_group_id=group_id,
                        conversion_group_add_count=len(split.pc_tracks),
                        conversion_source_fingerprints=(
                            (source.fingerprint,) if source.fingerprint else ()
                        ),
                        conversion_source_path_hints=(str(source.source_path),),
                    )
                )

            original_title = request.track.get("Title") or "chaptered track"
            remove_size = int(request.track.get("size", request.track.get("Size", 0)) or 0)
            remove_item = SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint=source.fingerprint,
                db_track_id=request.track.get("db_track_id", request.track.get("db_id")),
                ipod_track=request.track,
                description=f"Replace chaptered track: {original_title}",
                conversion_group_id=group_id,
                defer_removal_until_after_add=True,
            )

            plan = SyncPlan(
                to_add=add_items,
                to_remove=[remove_item],
                storage=StorageSummary(
                    bytes_to_add=bytes_to_add,
                    bytes_to_remove=remove_size,
                ),
                removals_pre_checked=True,
                mapping=mapping,
            )

            self.progress.emit(
                "chapter_split",
                len(segments),
                len(segments),
                "Chapter tracks are ready for review.",
            )
            self.finished.emit(
                ChapterSplitResult(
                    plan=plan,
                    output_paths=tuple(str(path) for path in split.output_paths),
                    warnings=tuple(source_warnings),
                )
            )
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("ChapterSplitWorker failed")
            self.error.emit(str(exc))

    @staticmethod
    def _output_dir(settings: AppSettings) -> Path:
        base = (
            Path(settings.transcode_cache_dir)
            if getattr(settings, "transcode_cache_dir", "")
            else Path(getattr(settings, "settings_dir", "") or tempfile.gettempdir())
        )
        return base / "chapter-splits"


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

    from SyncEngine._formats import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS

    extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS
    return path.is_file() and path.suffix.lower() in extensions


def has_supported_media_extension(path: Path, *, include_video: bool = True) -> bool:
    """Return whether a path name looks like a supported media file."""

    from SyncEngine._formats import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS

    extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS
    return path.suffix.lower() in extensions


def is_supported_photo_file(path: Path) -> bool:
    """Return whether a path is a supported photo import file."""

    from SyncEngine._formats import PHOTO_EXTENSIONS

    return path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS


def has_supported_photo_extension(path: Path) -> bool:
    """Return whether a path name looks like a supported photo import file."""

    from SyncEngine._formats import PHOTO_EXTENSIONS

    return path.suffix.lower() in PHOTO_EXTENSIONS


def is_supported_playlist_file(path: Path) -> bool:
    """Return whether a path is a supported playlist import file."""

    from SyncEngine._formats import PLAYLIST_EXTENSIONS

    return path.is_file() and path.suffix.lower() in PLAYLIST_EXTENSIONS


def has_supported_playlist_extension(path: Path) -> bool:
    """Return whether a path name looks like a supported playlist import file."""

    from SyncEngine._formats import PLAYLIST_EXTENSIONS

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


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path))


def _append_unique_path(paths: list[Path], seen: set[str], path: Path) -> None:
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
            _append_unique_path(track_paths, seen_tracks, candidate)
            return
        if include_photo and is_supported_photo_file(candidate):
            key = _path_key(candidate)
            if key not in seen_photos:
                seen_photos.add(key)
                photo_imports.append((str(candidate), album_name))
            return
        if include_playlist and is_supported_playlist_file(candidate):
            _append_unique_path(playlist_paths, seen_playlists, candidate)

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

    from SyncEngine.playlist_parser import parse_playlist, resolve_existing_playlist_path

    media_paths: list[Path] = []
    playlists: list[dict] = []
    seen_media: set[str] = set()

    for playlist_path in playlist_paths:
        try:
            raw_paths, playlist_name = parse_playlist(playlist_path)
        except Exception as exc:
            logger.warning("Failed to parse dropped playlist %s: %s", playlist_path, exc)
            continue

        items: list[dict] = []
        for raw_path in raw_paths:
            resolved_path = resolve_existing_playlist_path(raw_path)
            if resolved_path is None:
                continue
            path = Path(resolved_path)
            if not is_supported_media_file(path, include_video=include_video):
                continue
            _append_unique_path(media_paths, seen_media, path)
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


def build_imported_photo_edit_state(imported_files: Iterable[Any] | None) -> Any | None:
    """Build photo edit state for selectively imported photo files."""

    files = tuple(imported_files or ())
    if not files:
        return None

    from SyncEngine.photos import PhotoEditState

    photo_edits = PhotoEditState()
    photo_edits.imported_files.extend(files)
    return photo_edits


def build_podcast_plan_for_sync(
    feeds: list[Any],
    ipod_tracks: list,
    store: Any,
    *,
    supports_podcast: bool = True,
    fetch_feed_fn: Callable[..., Any] | None = None,
    build_plan_fn: Callable[..., Any] | None = None,
) -> Any:
    """Refresh podcast feeds and build the managed podcast sync plan."""

    if not supports_podcast:
        from SyncEngine.fingerprint_diff_engine import SyncPlan

        return SyncPlan()

    fetcher = fetch_feed_fn
    if fetcher is None:
        from PodcastManager.feed_parser import fetch_feed

        fetcher = fetch_feed

    builder = build_plan_fn
    if builder is None:
        from PodcastManager.podcast_sync import (
            build_podcast_managed_plan,
        )

        builder = build_podcast_managed_plan

    refreshed = []
    podcast_dir = getattr(store, "podcast_dir", "")
    cache_artwork = None
    if podcast_dir:
        try:
            from PodcastManager.artwork import cache_feed_artwork

            cache_artwork = cache_feed_artwork
        except Exception:
            cache_artwork = None

    for feed in feeds:
        try:
            refreshed_feed = fetcher(feed.feed_url, existing=feed)
            if cache_artwork is not None:
                cache_artwork(refreshed_feed, podcast_dir)
            refreshed.append(refreshed_feed)
        except Exception as exc:
            logger.warning(
                "Podcast refresh failed for %s: %s",
                getattr(feed, "title", "feed"),
                exc,
            )
            refreshed.append(feed)

    store.update_feeds(refreshed)
    return builder(refreshed, ipod_tracks, store)


@dataclass(frozen=True)
class PodcastPlanRequest:
    """Typed request for building managed podcast additions/removals."""

    feeds: list[Any]
    ipod_tracks: list
    store: Any
    supports_podcast: bool = True


class PodcastPlanWorker(QThread):
    """Background worker for managed podcast feed refresh and plan building."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, request: PodcastPlanRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            request = self._request
            plan = build_podcast_plan_for_sync(
                request.feeds,
                request.ipod_tracks,
                request.store,
                supports_podcast=request.supports_podcast,
            )
            if not self.isInterruptionRequested():
                self.finished.emit(plan)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("PodcastPlanWorker failed")
            self.error.emit(str(exc))


@dataclass(frozen=True)
class BackupDeviceContext:
    """Stable backup identity and metadata for a device."""

    device_id: str
    device_name: str
    device_meta: dict[str, str]


@dataclass(frozen=True)
class BackupDeviceInventory:
    """Known backup devices plus the currently connected device identity."""

    devices: list[dict[str, Any]]
    connected_device_id: str
    device_connected: bool


@dataclass(frozen=True)
class BackupSnapshotCatalog:
    """Snapshots and total storage for one backup device."""

    snapshots: list[Any]
    total_backup_size: int


def build_backup_device_meta(device_info: Any | None) -> dict[str, str]:
    """Return serializable device metadata for backup manifests and UI."""

    if device_info is None:
        return {}
    return {
        "family": str(getattr(device_info, "model_family", "") or ""),
        "generation": str(getattr(device_info, "generation", "") or ""),
        "color": str(getattr(device_info, "color", "") or ""),
        "display_name": str(getattr(device_info, "display_name", "") or ""),
    }


def build_backup_device_context(
    ipod_path: str,
    device_info: Any | None,
) -> BackupDeviceContext:
    """Return the sanitized backup identity for a connected device."""

    from SyncEngine.backup_manager import (
        BackupManager,
        get_device_display_name,
        get_device_identifier,
    )

    raw_id = get_device_identifier(ipod_path, device_info)
    return BackupDeviceContext(
        device_id=BackupManager._sanitize_id(raw_id),
        device_name=get_device_display_name(device_info),
        device_meta=build_backup_device_meta(device_info),
    )


def list_backup_devices_for_view(
    backup_dir: str,
    *,
    connected_ipod_path: str = "",
    connected_ipod_info: Any | None = None,
) -> BackupDeviceInventory:
    """Return backup devices sorted for the backup browser sidebar."""

    from SyncEngine.backup_manager import BackupManager

    devices_by_id = {
        item["device_id"]: dict(item)
        for item in BackupManager.list_all_devices(backup_dir)
    }
    connected_device_id = ""
    device_connected = bool(connected_ipod_path)

    if connected_ipod_path:
        context = build_backup_device_context(connected_ipod_path, connected_ipod_info)
        connected_device_id = context.device_id
        connected_info = devices_by_id.get(connected_device_id, {})
        connected_info.update(
            {
                "device_id": connected_device_id,
                "device_name": context.device_name,
                "snapshot_count": int(
                    connected_info.get("snapshot_count", 0) or 0
                ),
                "device_meta": (
                    context.device_meta
                    or connected_info.get("device_meta", {})
                ),
            }
        )
        devices_by_id[connected_device_id] = connected_info

    devices = sorted(
        devices_by_id.values(),
        key=lambda item: (
            0 if item.get("device_id") == connected_device_id else 1,
            str(item.get("device_name") or item.get("device_id") or "").lower(),
        ),
    )
    return BackupDeviceInventory(
        devices=devices,
        connected_device_id=connected_device_id,
        device_connected=device_connected,
    )


def load_backup_snapshot_catalog(
    device_id: str,
    backup_dir: str,
) -> BackupSnapshotCatalog:
    """Load snapshots and total backup size for one device."""

    from SyncEngine.backup_manager import BackupManager

    manager = BackupManager(device_id=device_id, backup_dir=backup_dir)
    return BackupSnapshotCatalog(
        snapshots=manager.list_snapshots(),
        total_backup_size=manager.get_backup_size(),
    )


def ensure_backup_folder(backup_dir: str, device_id: str = "") -> Path:
    """Create and return the backup folder, preferring a device subfolder."""

    from SyncEngine.backup_manager import _DEFAULT_BACKUP_DIR

    folder = Path(backup_dir or _DEFAULT_BACKUP_DIR)
    if device_id:
        device_folder = folder / device_id
        if device_folder.exists():
            folder = device_folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def delete_backup_snapshot(device_id: str, backup_dir: str, snapshot_id: str) -> bool:
    """Delete a backup snapshot for one device."""

    from SyncEngine.backup_manager import BackupManager

    manager = BackupManager(device_id=device_id, backup_dir=backup_dir)
    return bool(manager.delete_snapshot(snapshot_id))


@dataclass(frozen=True)
class BackupCreateRequest:
    """Typed request for creating a full device backup."""

    ipod_path: str
    device_id: str
    device_name: str
    backup_dir: str
    max_backups: int
    device_meta: dict[str, str]


class BackupCreateWorker(QThread):
    """Background worker for creating a device backup."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, request: BackupCreateRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            from SyncEngine.backup_manager import BackupManager

            request = self._request
            manager = BackupManager(
                device_id=request.device_id,
                backup_dir=request.backup_dir,
                device_name=request.device_name,
                device_meta=request.device_meta,
            )

            def on_progress(prog) -> None:
                self.progress.emit(
                    prog.stage,
                    prog.current,
                    prog.total,
                    prog.message,
                )

            result = manager.create_backup(
                ipod_path=request.ipod_path,
                progress_callback=on_progress,
                is_cancelled=self.isInterruptionRequested,
                max_backups=request.max_backups,
            )

            if result is None:
                try:
                    manager.garbage_collect()
                except Exception as exc:
                    logger.debug("Backup garbage collection failed: %s", exc)

            self.finished.emit(result)
        except Exception as exc:
            logger.exception("BackupCreateWorker failed")
            self.error.emit(str(exc))


@dataclass(frozen=True)
class BackupRestoreRequest:
    """Typed request for restoring one backup snapshot."""

    snapshot_id: str
    ipod_path: str
    device_id: str
    backup_dir: str


class BackupRestoreWorker(QThread):
    """Background worker for restoring a device backup snapshot."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, request: BackupRestoreRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:
        try:
            from SyncEngine.backup_manager import BackupManager

            request = self._request
            manager = BackupManager(
                device_id=request.device_id,
                backup_dir=request.backup_dir,
            )

            def on_progress(prog) -> None:
                self.progress.emit(
                    prog.stage,
                    prog.current,
                    prog.total,
                    prog.message,
                )

            success = manager.restore_backup(
                snapshot_id=request.snapshot_id,
                ipod_path=request.ipod_path,
                progress_callback=on_progress,
                is_cancelled=self.isInterruptionRequested,
            )

            self.finished.emit(success)
        except Exception as exc:
            logger.exception("BackupRestoreWorker failed")
            self.error.emit(str(exc))


@dataclass(frozen=True)
class SyncDiffRequest:
    """Typed request for computing a PC-vs-iPod sync diff."""

    pc_folder: str
    ipod_tracks: list
    pc_folders: tuple[Any, ...] = ()
    ipod_path: str = ""
    supports_video: bool = True
    supports_podcast: bool = True
    supports_photo: bool = True
    track_edits: dict | None = None
    photo_edits: Any = None
    sync_workers: int = 0
    rating_strategy: str = "ipod_wins"
    allowed_paths: frozenset[str] | None = None
    fpcalc_path: str = ""
    photo_sync_settings: dict[str, bool] | None = None
    transcode_options: Any = None


class SyncDiffWorker(QThread):
    """Background worker for computing a sync diff."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, request: SyncDiffRequest):
        super().__init__()
        self._request = request

    @staticmethod
    def _pc_folders(request: SyncDiffRequest) -> tuple[Any, ...]:
        folders = tuple(path for path in request.pc_folders if str(path).strip())
        if folders:
            return folders
        return (request.pc_folder,) if request.pc_folder else ()

    def run(self) -> None:
        try:
            from SyncEngine.fingerprint_diff_engine import FingerprintDiffEngine
            from SyncEngine.pc_library import PCLibrary

            request = self._request
            pc_library = PCLibrary(self._pc_folders(request))
            diff_engine = FingerprintDiffEngine(
                pc_library,
                request.ipod_path,
                supports_video=request.supports_video,
                supports_podcast=request.supports_podcast,
                supports_photo=request.supports_photo,
                fpcalc_path=request.fpcalc_path,
                photo_sync_settings=request.photo_sync_settings,
                transcode_options=request.transcode_options,
            )

            plan = diff_engine.compute_diff(
                request.ipod_tracks,
                progress_callback=lambda stage, cur, tot, msg: self.progress.emit(
                    stage,
                    cur,
                    tot,
                    msg,
                ),
                is_cancelled=self.isInterruptionRequested,
                track_edits=request.track_edits,
                photo_edits=request.photo_edits,
                sync_workers=request.sync_workers,
                rating_strategy=request.rating_strategy,
                allowed_paths=request.allowed_paths,
            )

            if not self.isInterruptionRequested():
                self.finished.emit(plan)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("SyncDiffWorker failed")
            self.error.emit(str(exc))


@dataclass(frozen=True)
class BackSyncRequest:
    """Typed request for exporting iPod-only tracks back to the PC library."""

    pc_folder: str
    ipod_tracks: list
    ipod_path: str
    pc_folders: tuple[Any, ...] = ()


class BackSyncWorker(QThread):
    """Background worker for Back Sync from iPod to PC."""

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        request: BackSyncRequest,
        artwork_provider: Callable[[dict], bytes | None] | None = None,
    ):
        super().__init__()
        self._request = request
        self._artwork_provider = artwork_provider
        from SyncEngine.unknown_metadata import UnknownMetadataRegistry
        self._unknown_registry = UnknownMetadataRegistry()

    @staticmethod
    def _short_label(value: str, limit: int = 72) -> str:
        text = str(value or "").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        keep = max(limit - 3, 8)
        return text[:keep] + "..."

    def run(self) -> None:
        try:
            from SyncEngine._formats import MEDIA_EXTENSIONS
            from SyncEngine.audio_fingerprint import get_or_compute_fingerprint
            from SyncEngine.pc_library import PCLibrary

            request = self._request
            self.progress.emit(
                "backsync_scan_pc",
                0,
                0,
                "Looking through your PC library for tracks that are already here.",
            )
            pc_folders = tuple(path for path in request.pc_folders if str(path).strip())
            if not pc_folders and request.pc_folder:
                pc_folders = (request.pc_folder,)
            pc_library = PCLibrary(pc_folders)
            pc_tracks = list(pc_library.scan(include_video=True))
            total_pc = len(pc_tracks)

            self.progress.emit(
                "backsync_pc_fingerprint",
                0,
                total_pc,
                (
                    f"Building fingerprints for {total_pc:,} PC track"
                    f"{'s' if total_pc != 1 else ''}."
                ),
            )
            pc_fps: set[str] = set()
            pc_fingerprint_errors: list[str] = []
            workers = min(os.cpu_count() or 4, 8)

            def _fp_pc(path: str) -> str | None:
                return get_or_compute_fingerprint(path, write_to_file=False)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_fp_pc, track.path): track
                    for track in pc_tracks
                }
                done = 0
                for fut in as_completed(futures):
                    if self.isInterruptionRequested():
                        for pending in futures:
                            pending.cancel()
                        return
                    done += 1
                    pc_track = futures[fut]
                    try:
                        fp = fut.result()
                    except Exception as exc:
                        fp = None
                        pc_fingerprint_errors.append(f"{pc_track.filename}: {exc}")
                    if fp:
                        pc_fps.add(fp)
                    if done == total_pc or done % 25 == 0:
                        self.progress.emit(
                            "backsync_pc_fingerprint",
                            done,
                            total_pc,
                            (
                                f"{done:,}/{total_pc:,} checked - "
                                f"{len(pc_fps):,} usable fingerprints - "
                                f"{self._short_label(pc_track.filename)}"
                            ),
                        )

            ipod_candidates: list[tuple[dict, Path]] = []
            unresolved_ipod_tracks = 0
            unsupported_ipod_tracks = 0
            for track in request.ipod_tracks:
                location = track.get("Location")
                if not location:
                    unresolved_ipod_tracks += 1
                    continue
                ipod_file = self._resolve_location_to_path(str(location))
                if ipod_file is None:
                    unresolved_ipod_tracks += 1
                    continue
                if ipod_file.suffix.lower() not in MEDIA_EXTENSIONS:
                    unsupported_ipod_tracks += 1
                    continue
                ipod_candidates.append((track, ipod_file))

            total_ipod = len(ipod_candidates)
            self.progress.emit(
                "backsync_ipod_fingerprint",
                0,
                total_ipod,
                (
                    f"Comparing {total_ipod:,} iPod media file"
                    f"{'s' if total_ipod != 1 else ''} against your PC library."
                ),
            )

            to_export: list[tuple[dict, Path]] = []
            ipod_fingerprint_errors: list[str] = []
            for idx, (track, ipod_file) in enumerate(ipod_candidates, start=1):
                if self.isInterruptionRequested():
                    return
                title = track.get("Title") or ipod_file.name
                try:
                    fp = get_or_compute_fingerprint(ipod_file, write_to_file=False)
                except Exception as exc:
                    fp = None
                    ipod_fingerprint_errors.append(f"{title}: {exc}")
                if fp and fp not in pc_fps:
                    to_export.append((track, ipod_file))
                self.progress.emit(
                    "backsync_ipod_fingerprint",
                    idx,
                    total_ipod,
                    (
                        f"{idx:,}/{total_ipod:,} checked - "
                        f"{len(to_export):,} missing so far - "
                        f"{self._short_label(title)}"
                    ),
                )

            pc_folder_paths = media_folder_paths(pc_folders)
            output_parent = pc_folder_paths[0] if pc_folder_paths else request.pc_folder
            output_root = Path(output_parent) / "iOpenPod Back Sync"
            output_root.mkdir(parents=True, exist_ok=True)

            exported = 0
            metadata_hydrated = 0
            artwork_hydrated = 0
            errors: list[str] = []
            total_export = len(to_export)

            self.progress.emit(
                "backsync_copy",
                0,
                total_export,
                (
                    f"Exporting {total_export:,} missing track"
                    f"{'s' if total_export != 1 else ''} to iOpenPod Back Sync."
                ),
            )

            for idx, (track, src_path) in enumerate(to_export, start=1):
                if self.isInterruptionRequested():
                    return
                try:
                    dest_path = self._build_destination_path(
                        output_root,
                        track,
                        src_path,
                    )
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_path)

                    art_bytes = self._extract_artwork_bytes(track)
                    wrote_meta, wrote_art = self._hydrate_file_metadata(
                        dest_path,
                        track,
                        art_bytes,
                    )
                    if wrote_meta:
                        metadata_hydrated += 1
                    if wrote_art:
                        artwork_hydrated += 1

                    exported += 1
                    self.progress.emit(
                        "backsync_copy",
                        idx,
                        total_export,
                        (
                            f"{idx:,}/{total_export:,} exported - "
                            f"{metadata_hydrated:,} tagged - "
                            f"{artwork_hydrated:,} with artwork - "
                            f"{self._short_label(dest_path.name)}"
                        ),
                    )
                except Exception as exc:
                    errors.append(f"{src_path.name}: {exc}")
                    self.progress.emit(
                        "backsync_copy",
                        idx,
                        total_export,
                        (
                            f"{idx:,}/{total_export:,} processed - "
                            f"{exported:,} exported - "
                            f"{len(errors):,} warning"
                            f"{'s' if len(errors) != 1 else ''} - "
                            f"{self._short_label(src_path.name)}"
                        ),
                    )

            self.finished.emit(
                {
                    "pc_scanned": total_pc,
                    "pc_fingerprint_count": len(pc_fps),
                    "pc_fingerprint_errors": pc_fingerprint_errors,
                    "ipod_scanned": total_ipod,
                    "unresolved_ipod_tracks": unresolved_ipod_tracks,
                    "unsupported_ipod_tracks": unsupported_ipod_tracks,
                    "ipod_fingerprint_errors": ipod_fingerprint_errors,
                    "missing_on_pc": total_export,
                    "exported": exported,
                    "metadata_hydrated": metadata_hydrated,
                    "artwork_hydrated": artwork_hydrated,
                    "output_folder": str(output_root),
                    "errors": errors,
                }
            )
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("BackSyncWorker failed")
            self.error.emit(str(exc))

    def _resolve_location_to_path(self, location: str) -> Path | None:
        if not location:
            return None

        loc = str(location).strip()
        direct = Path(loc)
        if direct.exists() and direct.is_file():
            return direct

        unified = loc.replace("\\", "/")
        marker_idx = unified.lower().find("ipod_control")
        if marker_idx >= 0:
            rel = unified[marker_idx:].lstrip("/")
            candidate = Path(self._request.ipod_path) / rel
            if candidate.exists() and candidate.is_file():
                return candidate

        is_windows_abs = len(loc) >= 3 and loc[1] == ":" and loc[2] in ("\\", "/")
        if not is_windows_abs and ":" in loc:
            rel = loc.replace(":", "/").lstrip("/")
            candidate = Path(self._request.ipod_path) / rel
            if candidate.exists() and candidate.is_file():
                return candidate

        fallback = Path(self._request.ipod_path) / unified.lstrip("/")
        if fallback.exists() and fallback.is_file():
            return fallback
        return None

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        text = (value or "").strip() or fallback
        text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", text)
        text = text.strip(" .")
        return (text or fallback)[:120]

    def _build_destination_path(
        self,
        output_root: Path,
        track: dict,
        src_path: Path,
    ) -> Path:
        from SyncEngine.unknown_metadata import apply_unknown_placeholders_to_mapping

        apply_unknown_placeholders_to_mapping(track, self._unknown_registry)

        artist = self._safe_component(
            track.get("Artist", "Unknown Artist"),
            "Unknown Artist",
        )
        album = self._safe_component(
            track.get("Album", "Unknown Album"),
            "Unknown Album",
        )
        title = self._safe_component(
            track.get("Title", src_path.stem),
            src_path.stem,
        )

        track_num = track.get("track_number", 0) or 0
        if track_num > 0:
            base_name = f"{track_num:02d} - {title}"
        else:
            base_name = title

        ext = src_path.suffix.lower()
        dest_dir = output_root / artist / album
        dest = dest_dir / f"{base_name}{ext}"

        if not dest.exists():
            return dest

        i = 2
        while True:
            alt = dest_dir / f"{base_name} ({i}){ext}"
            if not alt.exists():
                return alt
            i += 1

    def _extract_artwork_bytes(self, track: dict) -> bytes | None:
        if self._artwork_provider is None:
            return None
        try:
            return self._artwork_provider(track)
        except Exception as exc:
            logger.debug("Back Sync artwork provider failed: %s", exc)
            return None

    def _hydrate_file_metadata(
        self,
        file_path: Path,
        track: dict,
        art_bytes: bytes | None,
    ) -> tuple[bool, bool]:
        from SyncEngine.unknown_metadata import apply_unknown_placeholders_to_mapping

        apply_unknown_placeholders_to_mapping(track, self._unknown_registry)

        ext = file_path.suffix.lower()
        wrote_meta = False
        wrote_art = False

        title = track.get("Title")
        artist = track.get("Artist")
        album = track.get("Album")
        album_artist = track.get("Album Artist")
        genre = track.get("Genre")
        composer = track.get("Composer")
        comment = track.get("Comment")
        year = track.get("year", 0) or 0
        track_number = track.get("track_number", 0) or 0
        total_tracks = track.get("total_tracks", 0) or 0
        disc_number = track.get("disc_number", 0) or 0
        total_discs = track.get("total_discs", 0) or 0

        try:
            if ext in (".mp3", ".aif", ".aiff", ".wav"):
                from mutagen.id3 import ID3
                from mutagen.id3._frames import (
                    APIC,
                    COMM,
                    TALB,
                    TCOM,
                    TCON,
                    TDRC,
                    TIT2,
                    TPE1,
                    TPE2,
                    TPOS,
                    TRCK,
                )
                from mutagen.id3._util import ID3NoHeaderError

                try:
                    tags = ID3(str(file_path))
                except ID3NoHeaderError:
                    tags = ID3()

                def _set_text(fid: str, frame) -> None:
                    tags.delall(fid)
                    tags.add(frame)

                if title:
                    _set_text("TIT2", TIT2(encoding=3, text=[str(title)]))
                if artist:
                    _set_text("TPE1", TPE1(encoding=3, text=[str(artist)]))
                if album:
                    _set_text("TALB", TALB(encoding=3, text=[str(album)]))
                if album_artist:
                    _set_text("TPE2", TPE2(encoding=3, text=[str(album_artist)]))
                if genre:
                    _set_text("TCON", TCON(encoding=3, text=[str(genre)]))
                if composer:
                    _set_text("TCOM", TCOM(encoding=3, text=[str(composer)]))
                if year:
                    _set_text("TDRC", TDRC(encoding=3, text=[str(year)]))
                if track_number:
                    trk = (
                        f"{track_number}/{total_tracks}"
                        if total_tracks
                        else str(track_number)
                    )
                    _set_text("TRCK", TRCK(encoding=3, text=[trk]))
                if disc_number:
                    dsk = (
                        f"{disc_number}/{total_discs}"
                        if total_discs
                        else str(disc_number)
                    )
                    _set_text("TPOS", TPOS(encoding=3, text=[dsk]))
                if comment:
                    tags.delall("COMM")
                    tags.add(
                        COMM(
                            encoding=3,
                            lang="eng",
                            desc="",
                            text=[str(comment)],
                        )
                    )

                if art_bytes:
                    tags.delall("APIC")
                    tags.add(
                        APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=3,
                            desc="Cover",
                            data=art_bytes,
                        )
                    )
                    wrote_art = True

                tags.save(str(file_path))
                wrote_meta = True

            elif ext in (".m4a", ".m4p", ".aac", ".m4b", ".mp4", ".m4v", ".mov"):
                from mutagen.mp4 import MP4, MP4Cover

                audio = MP4(str(file_path))
                mp4_tags = audio.tags
                if mp4_tags is None:
                    audio.add_tags()
                    mp4_tags = audio.tags
                if mp4_tags is None:
                    return False, False

                if title:
                    mp4_tags["\xa9nam"] = [str(title)]
                if artist:
                    mp4_tags["\xa9ART"] = [str(artist)]
                if album:
                    mp4_tags["\xa9alb"] = [str(album)]
                if album_artist:
                    mp4_tags["aART"] = [str(album_artist)]
                if genre:
                    mp4_tags["\xa9gen"] = [str(genre)]
                if composer:
                    mp4_tags["\xa9wrt"] = [str(composer)]
                if comment:
                    mp4_tags["\xa9cmt"] = [str(comment)]
                if year:
                    mp4_tags["\xa9day"] = [str(year)]

                if track_number:
                    mp4_tags["trkn"] = [
                        (int(track_number), int(total_tracks or 0))
                    ]
                if disc_number:
                    mp4_tags["disk"] = [
                        (int(disc_number), int(total_discs or 0))
                    ]

                if art_bytes:
                    mp4_tags["covr"] = [
                        MP4Cover(art_bytes, imageformat=MP4Cover.FORMAT_JPEG)
                    ]
                    wrote_art = True

                audio.save()
                wrote_meta = True

        except Exception:
            return False, False

        return wrote_meta, wrote_art


class AutoRestoreDeviceWorker(QThread):
    """Identify the remembered iPod off the UI thread during startup."""

    found = pyqtSignal(str, object)
    not_found = pyqtSignal(str)
    failed = pyqtSignal(str, str)

    def __init__(self, remembered_path: str):
        super().__init__()
        self._remembered_path = remembered_path

    def run(self) -> None:
        path = self._remembered_path
        try:
            ipod_control = os.path.join(path, "iPod_Control")
            itunes_folder = os.path.join(ipod_control, "iTunes")
            is_virtual = False
            try:
                from ipod_device import has_virtual_ipod_info

                is_virtual = has_virtual_ipod_info(path)
            except Exception:
                is_virtual = False
            if (
                not is_virtual
                and (not os.path.isdir(ipod_control) or not os.path.isdir(itunes_folder))
            ):
                self.not_found.emit(path)
                return

            from ipod_device import identify_ipod_at_path

            ipod = identify_ipod_at_path(path)
            if self.isInterruptionRequested():
                return
            if ipod is None:
                self.not_found.emit(path)
                return
            self.found.emit(ipod.path or path, ipod)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(path, str(exc))


def scan_for_ipod_devices(
    scan_fn: Callable[[], list[Any] | None] | None = None,
) -> list[Any]:
    """Return currently discoverable iPod devices."""

    scanner = scan_fn
    if scanner is None:
        from ipod_device import scan_for_ipods

        scanner = scan_for_ipods

    return list(scanner() or [])


class DeviceScanWorker(QThread):
    """Background worker for scanning mounted volumes for iPods."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            ipods = scan_for_ipod_devices()
            if not self.isInterruptionRequested():
                self.finished.emit(ipods)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            logger.exception("DeviceScanWorker failed")
            self.error.emit(str(exc))


class EjectDeviceWorker(QThread):
    """Run the cross-platform safe eject off the UI thread."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, ipod_path: str):
        super().__init__()
        self._ipod_path = ipod_path

    def run(self) -> None:
        try:
            from ipod_device.eject import eject_ipod

            ok, message = eject_ipod(self._ipod_path)
            if ok:
                self.finished_ok.emit(message)
            else:
                self.failed.emit(message)
        except Exception as exc:
            logger.exception("EjectDeviceWorker: unexpected error")
            self.failed.emit(str(exc))


def _reload_after_itunesdb_write(cache: LibraryCacheLike) -> None:
    cache.reload_after_itunesdb_write()


def _snapshot_cache_for_itunesdb_write(
    cache: LibraryCacheLike,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, str]]:
    tracks = copy.deepcopy(cache.get_tracks())
    artwork_sources = copy.deepcopy(cache.get_track_artwork_edits())
    for track in tracks:
        track.pop("_iop_pending_artwork_path", None)
    playlists = copy.deepcopy(cache.get_playlists())
    return tracks, playlists, artwork_sources


class QuickWriteWorker(QThread):
    """Background worker that dumps the current cached iTunesDB snapshot."""

    completed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        ipod_path: str,
        cache: LibraryCacheLike,
    ):
        super().__init__()
        self._ipod_path = ipod_path
        self._cache = cache
        (
            self._tracks_data,
            self._playlists_data,
            self._artwork_sources,
        ) = _snapshot_cache_for_itunesdb_write(cache)

    def run(self) -> None:
        try:
            from SyncEngine.quick_writes import write_cached_itunesdb

            result = write_cached_itunesdb(
                self._ipod_path,
                tracks_data=self._tracks_data,
                playlists_data=self._playlists_data,
                artwork_sources=self._artwork_sources,
            )

            _reload_after_itunesdb_write(self._cache)
            self.completed.emit(result)
        except Exception as exc:
            logger.exception("QuickWriteWorker failed")
            _reload_after_itunesdb_write(self._cache)
            self.error.emit(str(exc))


class PlaylistWriteWorker(QThread):
    """Background worker for writing one edited playlist to the iPod."""

    finished_ok = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(self, playlist: dict, ipod_path: str, cache: LibraryCacheLike):
        super().__init__()
        self._playlist = playlist
        self._ipod_path = ipod_path
        self._cache = cache

    def run(self) -> None:
        try:
            from SyncEngine.quick_writes import write_cached_itunesdb

            if not self._ipod_path:
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit("No iPod connected.")
                return
            if not self._cache.get_data():
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit("No iPod database loaded.")
                return

            tracks_data, playlists_data, artwork_sources = (
                _snapshot_cache_for_itunesdb_write(self._cache)
            )
            result = write_cached_itunesdb(
                self._ipod_path,
                tracks_data=tracks_data,
                playlists_data=playlists_data,
                artwork_sources=artwork_sources,
            )
            if not result.success:
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit(result.error or "Database write failed.")
                return

            _delete_imported_otg_files(self._ipod_path)
            playlist_id = int(self._playlist.get("playlist_id", 0) or 0)
            matched_count = result.playlist_counts.get(playlist_id, 0)
            playlist_name = str(self._playlist.get("Title", "Untitled"))
            _reload_after_itunesdb_write(self._cache)
            self.finished_ok.emit(matched_count, playlist_name)
        except Exception as exc:
            logger.exception("PlaylistWriteWorker failed")
            _reload_after_itunesdb_write(self._cache)
            self.failed.emit(str(exc))


class PlaylistDeleteWorker(QThread):
    """Background worker for deleting one playlist from the iPod."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, playlist: dict, ipod_path: str, cache: LibraryCacheLike):
        super().__init__()
        self._playlist = playlist
        self._ipod_path = ipod_path
        self._cache = cache

    def run(self) -> None:
        try:
            from SyncEngine.quick_writes import write_cached_itunesdb

            if not self._ipod_path:
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit("No iPod connected.")
                return
            if not self._cache.get_data():
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit("No iPod database loaded.")
                return

            tracks_data, playlists_data, artwork_sources = (
                _snapshot_cache_for_itunesdb_write(self._cache)
            )
            result = write_cached_itunesdb(
                self._ipod_path,
                tracks_data=tracks_data,
                playlists_data=playlists_data,
                artwork_sources=artwork_sources,
            )
            if not result.success:
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit(result.error or "Database write failed.")
                return

            _reload_after_itunesdb_write(self._cache)
            self.finished_ok.emit(str(self._playlist.get("Title", "Untitled")))
        except Exception as exc:
            logger.exception("PlaylistDeleteWorker failed")
            _reload_after_itunesdb_write(self._cache)
            self.failed.emit(str(exc))


class PlaylistImportWorker(QThread):
    """Background worker for importing a playlist file into the iPod."""

    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(str, int, int, int)
    failed = pyqtSignal(str)

    def __init__(
        self,
        playlist_file: str,
        ipod_path: str,
        fpcalc_path: str,
        cache: LibraryCacheLike,
    ):
        super().__init__()
        self._playlist_file = playlist_file
        self._ipod_path = ipod_path
        self._fpcalc_path = fpcalc_path or None
        self._cache = cache

    def run(self) -> None:
        cache_mutated = False
        try:
            from SyncEngine.audio_fingerprint import get_or_compute_fingerprint
            from SyncEngine.contracts import SyncRequest
            from SyncEngine.fingerprint_diff_engine import (
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from SyncEngine.mapping import MappingManager
            from SyncEngine.pc_library import PCLibrary
            from SyncEngine.playlist_parser import (
                parse_playlist,
                resolve_existing_playlist_path,
            )
            from SyncEngine.quick_writes import write_cached_itunesdb
            from SyncEngine.sync_executor import SyncExecutor

            self.progress.emit(0, 0, "Parsing playlist file...")
            try:
                raw_paths, playlist_name = parse_playlist(self._playlist_file)
            except Exception as exc:
                self.failed.emit(f"Failed to parse playlist: {exc}")
                return

            if not raw_paths:
                self.failed.emit("Playlist contains no tracks.")
                return

            existing_paths: list[str] = []
            skipped = 0
            for raw_path in raw_paths:
                resolved_path = resolve_existing_playlist_path(raw_path)
                if resolved_path is None:
                    skipped += 1
                    continue
                existing_paths.append(resolved_path)

            total = len(existing_paths)
            if not existing_paths:
                self.failed.emit(
                    "None of the playlist files could be found on this PC."
                )
                return

            self.progress.emit(0, total, f"Scanning {total} tracks...")

            ipod_root = Path(self._ipod_path)
            track_id_index = self._cache.get_track_id_index()
            loc_to_db_track_id: dict[str, int] = {}
            for track in track_id_index.values():
                loc = track.get("Location", "")
                db_track_id = track.get("db_track_id", track.get("db_id"))
                if loc and db_track_id:
                    loc_to_db_track_id[loc.lower()] = db_track_id

            def _path_to_location(path: Path) -> str:
                try:
                    rel = path.relative_to(ipod_root)
                except ValueError:
                    return ""
                return ":" + str(rel).replace("\\", ":").replace("/", ":")

            playlist_db_track_ids: list[int] = []
            needs_fingerprint: list[str] = []
            already_present_fps: list[str] = []
            fast_path_count = 0

            for idx, raw_path in enumerate(existing_paths):
                path = Path(raw_path)
                loc = _path_to_location(path)
                if loc:
                    db_track_id = loc_to_db_track_id.get(loc.lower())
                    if db_track_id is not None:
                        playlist_db_track_ids.append(db_track_id)
                        fast_path_count += 1
                        self.progress.emit(idx + 1, total, f"On iPod: {path.name}")
                        continue
                needs_fingerprint.append(raw_path)
                self.progress.emit(idx + 1, total, f"Needs ID check: {path.name}")

            to_add: list[SyncItem] = []
            if needs_fingerprint:
                mapping = MappingManager(self._ipod_path).load()
                fingerprint_total = len(needs_fingerprint)

                for idx, raw_path in enumerate(needs_fingerprint):
                    path = Path(raw_path)
                    global_idx = fast_path_count + idx + 1
                    self.progress.emit(
                        global_idx,
                        total,
                        (
                            f"Identifying ({idx + 1} of {fingerprint_total}): "
                            f"{path.name}"
                        ),
                    )

                    fingerprint = get_or_compute_fingerprint(
                        raw_path,
                        self._fpcalc_path,
                    )
                    if fingerprint is None:
                        skipped += 1
                        continue

                    if mapping.get_entries(fingerprint):
                        already_present_fps.append(fingerprint)
                        self.progress.emit(
                            global_idx,
                            total,
                            f"Already on iPod: {path.name}",
                        )
                        continue

                    self.progress.emit(
                        global_idx,
                        total,
                        f"New track, will add: {path.name}",
                    )
                    library = PCLibrary(str(path.parent))
                    pc_track = library._read_track(path)
                    if pc_track is None:
                        skipped += 1
                        continue

                    to_add.append(
                        SyncItem(
                            action=SyncAction.ADD_TO_IPOD,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                        )
                    )

            if to_add:
                add_count = len(to_add)
                self.progress.emit(
                    0,
                    add_count,
                    f"Adding {add_count} track(s) to iPod...",
                )

                def _on_sync_progress(progress) -> None:
                    message = progress.message or ""
                    if progress.current and progress.total:
                        self.progress.emit(progress.current, progress.total, message)
                    else:
                        self.progress.emit(progress.current or 0, add_count, message)

                fresh_mapping = MappingManager(self._ipod_path).load()
                plan = SyncPlan()
                plan.to_add.extend(to_add)
                request = SyncRequest(
                    plan=plan,
                    mapping=fresh_mapping,
                    progress_callback=_on_sync_progress,
                )
                result = SyncExecutor(self._ipod_path).execute_request(request)
                if not result.success:
                    error = result.errors[0] if result.errors else "Unknown error"
                    self.failed.emit(f"Sync failed: {error}")
                    return

            if already_present_fps or to_add:
                self.progress.emit(0, 0, "Resolving track IDs...")
                final_mapping = MappingManager(self._ipod_path).load()

                for fingerprint in already_present_fps:
                    entries = final_mapping.get_entries(fingerprint)
                    if entries:
                        playlist_db_track_ids.append(entries[0].db_track_id)

                for item in to_add:
                    if item.fingerprint is None:
                        continue
                    entries = final_mapping.get_entries(item.fingerprint)
                    if entries:
                        playlist_db_track_ids.append(entries[0].db_track_id)

            if not playlist_db_track_ids:
                self.failed.emit("No tracks could be matched to iPod database IDs.")
                return

            self.progress.emit(0, 0, f"Writing playlist '{playlist_name}'...")

            playlist_items = [
                {"db_track_id": int(db_track_id)}
                for db_track_id in playlist_db_track_ids
                if db_track_id
            ]
            if not playlist_items:
                self.failed.emit("No tracks could be mapped to iPod database IDs.")
                return

            playlist_id = random.getrandbits(64)
            playlist = {
                "Title": playlist_name,
                "playlist_id": playlist_id,
                "_isNew": True,
                "_source": "regular",
                "items": playlist_items,
            }
            self._cache.save_user_playlist(playlist)
            cache_mutated = True

            tracks_data, playlists_data, artwork_sources = (
                _snapshot_cache_for_itunesdb_write(self._cache)
            )
            if to_add:
                from SyncEngine._db_io import read_existing_database

                fresh_db = read_existing_database(Path(self._ipod_path))
                tracks_data = copy.deepcopy(fresh_db.get("tracks", []))
                playlists_data = copy.deepcopy(self._cache.get_playlists())
            write_result = write_cached_itunesdb(
                self._ipod_path,
                tracks_data=tracks_data,
                playlists_data=playlists_data,
                artwork_sources=artwork_sources,
            )
            if not write_result.success:
                _reload_after_itunesdb_write(self._cache)
                self.failed.emit(write_result.error or "Database write failed.")
                return

            _reload_after_itunesdb_write(self._cache)
            self.finished_ok.emit(
                playlist_name,
                len(to_add),
                fast_path_count + len(already_present_fps),
                skipped,
            )
        except Exception as exc:
            logger.exception("PlaylistImportWorker failed")
            if cache_mutated:
                _reload_after_itunesdb_write(self._cache)
            self.failed.emit(str(exc))


def _delete_imported_otg_files(ipod_path: str) -> None:
    try:
        from iTunesDB_Parser.otg import delete_otg_files

        delete_otg_files(os.path.join(str(ipod_path), "iPod_Control", "iTunes"))
    except Exception as exc:
        logger.debug("OTG cleanup after playlist write failed: %s", exc)


class SyncExecuteWorker(QThread):
    """Background worker for executing a reviewed sync plan."""

    progress = pyqtSignal(object)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    confirm_partial_save = pyqtSignal(int, int)

    def __init__(
        self,
        ipod_path: str,
        plan: Any,
        *,
        settings: AppSettings,
        skip_backup: bool = False,
        user_playlists: list | None = None,
        device_info: DeviceIdentitySnapshot | None = None,
        device_capabilities: DeviceCapabilitySnapshot | None = None,
        on_sync_complete: Callable[[], None] | None = None,
    ):
        super().__init__()
        self.ipod_path = ipod_path
        self.plan = plan
        self.skip_backup = skip_backup
        self._skip_backup_requested = False
        self.user_playlists = user_playlists
        self.settings = settings
        self.device_info = device_info
        self.device_capabilities = device_capabilities
        self.on_sync_complete = on_sync_complete
        self._give_up_scrobble_requested = False
        self._partial_save_event: threading.Event | None = None
        self._partial_save_decision: list[bool] = [True]

    def respond_to_partial_save(self, save: bool) -> None:
        """Unblock the worker after the UI decides on a partial save."""
        self._partial_save_decision[0] = save
        if self._partial_save_event:
            self._partial_save_event.set()

    def request_skip_backup(self) -> None:
        """Signal the worker to skip the in-progress backup."""
        self._skip_backup_requested = True

    def request_give_up_scrobble(self) -> None:
        """Signal the worker to stop retrying ListenBrainz scrobbles."""
        self._give_up_scrobble_requested = True

    def run(self) -> None:
        try:
            from SyncEngine.contracts import SyncProgress, SyncRequest
            from SyncEngine.mapping import MappingManager
            from SyncEngine.sync_executor import SyncExecutor

            settings = self.settings
            self._partial_save_event = threading.Event()

            def _on_cancel_with_partial(n_added: int, n_skipped: int) -> bool:
                evt = self._partial_save_event
                if evt is None:
                    return True
                self._partial_save_decision[0] = True
                evt.clear()
                self.confirm_partial_save.emit(n_added, n_skipped)
                evt.wait()
                return self._partial_save_decision[0]

            if not self.skip_backup:
                self._create_presync_backup(settings, SyncProgress)

            cache_dir = (
                Path(settings.transcode_cache_dir)
                if settings.transcode_cache_dir
                else None
            )
            executor = SyncExecutor(
                self.ipod_path,
                cache_dir=cache_dir,
                max_workers=settings.sync_workers,
                max_device_write_workers=settings.device_write_workers,
                max_cache_size_gb=settings.max_cache_size_gb,
                fpcalc_path=settings.fpcalc_path,
                transcode_options=build_transcode_options(settings),
                device_info=self.device_info,
                device_capabilities=self.device_capabilities,
                photo_sync_settings={
                    "rotate_tall_photos_for_device": (
                        settings.rotate_tall_photos_for_device
                    ),
                    "fit_photo_thumbnails": settings.fit_photo_thumbnails,
                },
            )

            if getattr(self.plan, "mapping", None) is not None:
                mapping = self.plan.mapping
            else:
                mapping_manager = MappingManager(self.ipod_path)
                mapping = mapping_manager.load()

            def on_progress(prog: SyncProgress) -> None:
                self.progress.emit(prog)

            request = SyncRequest(
                plan=self.plan,
                mapping=mapping,
                progress_callback=on_progress,
                dry_run=False,
                is_cancelled=self.isInterruptionRequested,
                write_back_to_pc=settings.write_back_to_pc,
                user_playlists=tuple(self.user_playlists or ()),
                on_sync_complete=self.on_sync_complete,
                compute_sound_check=settings.compute_sound_check,
                scrobble_on_sync=settings.scrobble_on_sync,
                listenbrainz_token=settings.listenbrainz_token or "",
                listenbrainz_username=settings.listenbrainz_username or "",
                is_scrobble_cancelled=lambda: self._give_up_scrobble_requested,
                on_cancel_with_partial=_on_cancel_with_partial,
            )

            self.finished.emit(executor.execute_request(request))
        except Exception as exc:
            logger.exception("SyncExecuteWorker failed")
            self.error.emit(str(exc))

    def _create_presync_backup(self, settings: AppSettings, progress_type) -> None:
        try:
            self.progress.emit(
                progress_type("backup", 0, 0, message="Creating pre-sync backup...")
            )
            from SyncEngine.backup_manager import (
                BackupManager,
                get_device_display_name,
                get_device_identifier,
            )

            device_id = get_device_identifier(self.ipod_path, self.device_info)
            device_name = get_device_display_name(self.device_info)
            ipod = self.device_info
            device_meta = {}
            if ipod:
                device_meta = {
                    "family": ipod.model_family,
                    "generation": ipod.generation,
                    "color": ipod.color,
                    "display_name": ipod.display_name,
                }

            manager = BackupManager(
                device_id=device_id,
                backup_dir=settings.backup_dir,
                device_name=device_name,
                device_meta=device_meta,
            )

            def on_backup_progress(prog) -> None:
                self.progress.emit(
                    progress_type(
                        "backup",
                        prog.current,
                        prog.total,
                        message=prog.message,
                    )
                )

            snap = manager.create_backup(
                ipod_path=self.ipod_path,
                progress_callback=on_backup_progress,
                is_cancelled=lambda: (
                    self.isInterruptionRequested() or self._skip_backup_requested
                ),
                max_backups=settings.max_backups,
            )

            if snap is None and self.isInterruptionRequested():
                return
            if snap is None:
                try:
                    manager.garbage_collect()
                except Exception as exc:
                    logger.debug("Backup garbage collection failed: %s", exc)
            else:
                logger.info("Pre-sync backup created: %s", snap.id)
        except Exception as exc:
            logger.warning("Pre-sync backup failed (continuing sync): %s", exc)
            logger.debug("Pre-sync backup failure details:\n%s", traceback.format_exc())


class DropScanWorker(QThread):
    """Read metadata from dropped files and build a sync plan."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        file_paths: list[Path],
        *,
        photo_imports: Iterable[tuple[str, str]] | None = None,
        playlist_paths: Iterable[Path] | None = None,
        ipod_path: str = "",
        supports_video: bool = True,
        supports_podcast: bool = True,
        supports_photo: bool = True,
        photo_sync_settings: dict[str, bool] | None = None,
    ):
        super().__init__()
        self._file_paths = file_paths
        self._photo_imports = tuple(photo_imports or ())
        self._playlist_paths = tuple(playlist_paths or ())
        self._ipod_path = ipod_path
        self._supports_video = supports_video
        self._supports_podcast = supports_podcast
        self._supports_photo = supports_photo
        self._photo_sync_settings = photo_sync_settings

    def run(self) -> None:
        try:
            from SyncEngine.capability_filter import is_track_supported_by_device
            from SyncEngine.fingerprint_diff_engine import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from SyncEngine.pc_library import PCLibrary

            items: list[SyncItem] = []
            total_bytes = 0
            playlist_media_paths, playlists_to_add = build_dropped_playlist_imports(
                self._playlist_paths,
                include_video=self._supports_video,
            )
            media_paths: list[Path] = []
            seen_media: set[str] = set()
            for path in (*self._file_paths, *playlist_media_paths):
                _append_unique_path(media_paths, seen_media, path)

            for path in media_paths:
                if self.isInterruptionRequested():
                    return
                try:
                    library = PCLibrary(path.parent)
                    track = library._read_track(path)
                    if track and is_track_supported_by_device(
                        track,
                        supports_video=self._supports_video,
                        supports_podcast=self._supports_podcast,
                    ):
                        items.append(
                            SyncItem(
                                action=SyncAction.ADD_TO_IPOD,
                                pc_track=track,
                                description=f"{track.artist} - {track.title}",
                            )
                        )
                        total_bytes += track.size
                except Exception as exc:
                    logger.warning("Failed to read dropped file %s: %s", path, exc)

            plan = SyncPlan()
            plan.to_add.extend(items)
            plan.playlists_to_add.extend(playlists_to_add)
            plan.storage = StorageSummary(bytes_to_add=total_bytes)
            if (
                self._supports_photo
                and self._photo_imports
                and self._ipod_path
            ):
                from SyncEngine.photos import (
                    build_photo_library_from_device,
                    build_photo_sync_plan,
                    ensure_photo_visual_hashes,
                    read_photo_db,
                )

                photo_edits = build_imported_photo_edit_state(self._photo_imports)
                if photo_edits is not None:
                    device_photos = read_photo_db(self._ipod_path)
                    ensure_photo_visual_hashes(device_photos, self._ipod_path)
                    desired_library = build_photo_library_from_device(device_photos)
                    plan.photo_plan = build_photo_sync_plan(
                        desired_library,
                        device_photos,
                        photo_edits,
                        ipod_path=self._ipod_path,
                        sync_settings=self._photo_sync_settings,
                    )
                    if plan.photo_plan is not None:
                        plan.storage.bytes_to_add += plan.photo_plan.thumb_bytes_to_add
                        plan.storage.bytes_to_remove += plan.photo_plan.thumb_bytes_to_remove
            self.finished.emit(plan)
        except Exception as exc:
            self.error.emit(str(exc))
            logger.debug("Drop scan failed:\n%s", traceback.format_exc())
