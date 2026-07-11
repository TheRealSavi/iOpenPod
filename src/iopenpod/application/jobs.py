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
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, SupportsInt, cast

from PyQt6.QtCore import QThread, pyqtSignal

from iopenpod.infrastructure.media_folders import media_folder_paths

from .dropped_files import (
    append_unique_path,
    build_dropped_playlist_imports,
)
from .sync_options import build_transcode_options

if TYPE_CHECKING:
    from iopenpod.infrastructure.settings_schema import AppSettings

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
        return False

    @property
    def tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.missing_fpcalc:
            names.append("fpcalc (Chromaprint)")
        if self.missing_ffmpeg:
            names.append("FFmpeg/ffprobe")
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
                "FFmpeg and ffprobe are required for transcoding and media probing.\n"
                "Install from: https://ffmpeg.org"
            )
        lines.append("You can also set custom paths in\nSettings -> External Tools.")
        return "\n\n".join(lines)


def check_sync_tool_availability(settings: AppSettings) -> SyncToolAvailability:
    """Return external tool availability for a full PC sync."""

    from iopenpod.sync.audio_fingerprint import is_fpcalc_available
    from iopenpod.sync.dependency_manager import is_platform_supported
    from iopenpod.sync.transcoder import is_ffmpeg_available

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
            from iopenpod.sync.dependency_manager import download_ffmpeg, download_fpcalc

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
            from iopenpod.sync.album_chapters import (
                convert_album_to_chaptered_track,
                resolve_album_sources,
            )
            from iopenpod.sync.contracts import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from iopenpod.sync.mapping import MappingManager
            from iopenpod.sync.source_identity import source_content_hash

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
                conversion_source_metadata=tuple(
                    {
                        "fingerprint": source.fingerprint,
                        "source_path_hint": str(source.source_path),
                        "source_size": source.source_path.stat().st_size,
                        "source_mtime": source.source_path.stat().st_mtime,
                        "source_hash": self._source_hash(source.source_path, source_content_hash),
                        "album_key": str(track.get("Album") or "").strip().lower(),
                        "title": str(track.get("Title") or ""),
                        "artist": str(track.get("Artist") or ""),
                        "album": str(track.get("Album") or ""),
                        "disc_number": int(track.get("disc_number") or 1),
                        "track_number": int(track.get("track_number") or index),
                        "startpos": int(chapter.get("startpos") or 0),
                        "endpos": int(chapter.get("endpos") or 0),
                    }
                    for index, (track, source, chapter) in enumerate(
                        zip(request.album_tracks, sources, converted.chapters, strict=False),
                        start=1,
                    )
                    if source.fingerprint
                ),
                aggregate_kind="chaptered_album",
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

    @staticmethod
    def _source_hash(path: Path, source_content_hash_fn) -> str | None:
        try:
            return source_content_hash_fn(path)
        except OSError:
            return None


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
            from iopenpod.sync.album_chapters import (
                build_chapter_split_segments,
                resolve_track_source,
                split_track_into_chapter_tracks,
            )
            from iopenpod.sync.contracts import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from iopenpod.sync.mapping import MappingManager

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
            aggregate_mapping = self._aggregate_mapping_for_track(mapping, request.track)
            aggregate_fp = aggregate_mapping[0] if aggregate_mapping else source.fingerprint
            aggregate_source_rows = self._aggregate_source_rows_for_split(
                aggregate_mapping,
                len(split.pc_tracks),
            )
            add_items: list[SyncItem] = []
            bytes_to_add = 0
            for index, (pc_track, output_path) in enumerate(
                zip(split.pc_tracks, split.output_paths, strict=False)
            ):
                output_size = output_path.stat().st_size
                bytes_to_add += output_size
                source_meta = (
                    aggregate_source_rows[index]
                    if index < len(aggregate_source_rows)
                    else None
                )
                source_fp = (
                    str(source_meta.get("fingerprint") or "").strip()
                    if source_meta else None
                )
                add_items.append(
                    SyncItem(
                        action=SyncAction.ADD_TO_IPOD,
                        fingerprint=source_fp or None,
                        pc_track=pc_track,
                        estimated_size=output_size,
                        description=f"Split chapter: {pc_track.title}",
                        conversion_group_id=group_id,
                        conversion_group_add_count=len(split.pc_tracks),
                        mapping_source_metadata=source_meta,
                    )
                )

            original_title = request.track.get("Title") or "chaptered track"
            remove_size = int(request.track.get("size", request.track.get("Size", 0)) or 0)
            remove_item = SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint=aggregate_fp,
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
    def _aggregate_mapping_for_track(mapping, track: dict):
        db_track_id = track.get("db_track_id", track.get("db_id"))
        if not db_track_id:
            return None
        mapped = mapping.get_by_db_track_id(db_track_id)
        if not mapped:
            return None
        _fp, entry = mapped
        if entry.aggregate_kind != "chaptered_album":
            return None
        return mapped

    @staticmethod
    def _aggregate_source_rows_for_split(
        aggregate_mapping,
        segment_count: int,
    ) -> tuple[dict, ...]:
        if not aggregate_mapping:
            return ()
        _fp, entry = aggregate_mapping
        rows = [dict(row) for row in (entry.contains_sources or [])]
        if rows:
            rows.sort(key=lambda row: int(row.get("startpos") or 0))
            return tuple(rows) if len(rows) == segment_count else ()

        fingerprints = [fp for fp in (entry.contains_fingerprints or []) if fp]
        if len(fingerprints) != segment_count:
            return ()
        return tuple({"fingerprint": fp} for fp in fingerprints)

    @staticmethod
    def _output_dir(settings: AppSettings) -> Path:
        base = (
            Path(settings.transcode_cache_dir)
            if getattr(settings, "transcode_cache_dir", "")
            else Path(getattr(settings, "settings_dir", "") or tempfile.gettempdir())
        )
        return base / "chapter-splits"


def build_imported_photo_edit_state(imported_files: Iterable[Any] | None) -> Any | None:
    """Build photo edit state for selectively imported photo files."""

    files = tuple(imported_files or ())
    if not files:
        return None

    from iopenpod.sync.photos import PhotoEditState

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
        from iopenpod.sync.contracts import SyncPlan

        return SyncPlan()

    fetcher = fetch_feed_fn
    if fetcher is None:
        from iopenpod.podcasts.feed_parser import fetch_feed

        fetcher = fetch_feed

    builder = build_plan_fn
    if builder is None:
        from iopenpod.podcasts.podcast_sync import (
            build_podcast_managed_plan,
        )

        builder = build_podcast_managed_plan

    refreshed = []
    podcast_dir = getattr(store, "podcast_dir", "")
    cache_artwork = None
    if podcast_dir:
        try:
            from iopenpod.podcasts.artwork import cache_feed_artwork

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


def backup_device_name_from_playlists(playlists: Iterable[dict]) -> str:
    """Return the iPod name stored on the master playlist, if available."""

    for playlist in playlists:
        if playlist.get("master_flag") and not _is_ipod_category_playlist(playlist):
            return str(playlist.get("Title") or "").strip()
    return ""


def _mhsd5_type_value(playlist: dict) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_ipod_category_playlist(playlist: dict) -> bool:
    try:
        dataset_type = int(playlist.get("_mhsd_dataset_type", 0) or 0)
    except (TypeError, ValueError):
        dataset_type = 0
    if dataset_type:
        return dataset_type == 5
    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _int_or_zero(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, (str, bytes, bytearray, SupportsInt)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _track_db_track_id(track: dict) -> int:
    return _int_or_zero(track.get("db_track_id", track.get("db_id", 0)))


def _playlist_item_db_track_id(
    item: dict,
    old_tid_to_db_track_id: dict[int, int],
) -> int:
    db_track_id = _int_or_zero(item.get("db_track_id", item.get("db_id", 0)))
    if db_track_id:
        return db_track_id
    track_id = _int_or_zero(item.get("track_id", 0))
    return old_tid_to_db_track_id.get(track_id, 0)


def _old_tid_to_db_track_id(tracks: Iterable[dict]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in tracks:
        track_id = _int_or_zero(track.get("track_id", 0))
        db_track_id = _track_db_track_id(track)
        if track_id and db_track_id:
            result[track_id] = db_track_id
    return result


def _playlist_title_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _is_regular_import_target_playlist(playlist: dict) -> bool:
    if playlist.get("master_flag"):
        return False
    if playlist.get("smart_playlist_data") or playlist.get("smart_playlist_rules"):
        return False
    if playlist.get("podcast_flag") or playlist.get("_source") == "podcast":
        return False
    if _is_ipod_category_playlist(playlist):
        return False
    return True


def _find_import_target_playlist(
    playlists: Iterable[dict],
    playlist_name: str,
) -> dict | None:
    target_key = _playlist_title_key(playlist_name)
    if not target_key:
        return None
    for playlist in playlists:
        if not _is_regular_import_target_playlist(playlist):
            continue
        if _playlist_title_key(playlist.get("Title")) == target_key:
            return playlist
    return None


def _fresh_standard_playlists(fresh_db: dict) -> list[dict]:
    playlists: list[dict] = []
    for playlist in fresh_db.get("dataset2_standard_playlists", []) or []:
        row = dict(playlist)
        row.setdefault("_mhsd_dataset_type", 2)
        row.setdefault("_mhsd_result_key", "mhlp")
        playlists.append(row)
    return playlists


def _merged_playlist_items(
    existing_items: Iterable[dict],
    imported_db_track_ids: Iterable[int],
    tracks: Iterable[dict],
) -> list[dict]:
    old_tid_to_db_track_id = _old_tid_to_db_track_id(tracks)
    merged: list[dict] = []
    seen_db_track_ids: set[int] = set()

    for item in existing_items:
        if not isinstance(item, dict):
            continue
        merged_item = dict(item)
        merged.append(merged_item)
        db_track_id = _playlist_item_db_track_id(
            merged_item,
            old_tid_to_db_track_id,
        )
        if db_track_id:
            seen_db_track_ids.add(db_track_id)

    for db_track_id in imported_db_track_ids:
        normalized_id = _int_or_zero(db_track_id)
        if not normalized_id or normalized_id in seen_db_track_ids:
            continue
        merged.append({"db_track_id": normalized_id})
        seen_db_track_ids.add(normalized_id)

    return merged


def _import_source_path_key(path: object) -> str:
    try:
        from iopenpod.sync.path_identity import stable_path_key

        return stable_path_key(str(path))
    except (TypeError, ValueError, OSError):
        return str(path or "").strip().casefold()


def _merged_playlist_source_items(
    existing_items: Iterable[dict],
    imported_items: Iterable[dict],
    *,
    source_path_to_db_track_id: dict[str, int],
    tracks: Iterable[dict],
) -> list[dict]:
    old_tid_to_db_track_id = _old_tid_to_db_track_id(tracks)
    merged: list[dict] = []
    seen_db_track_ids: set[int] = set()
    seen_source_paths: set[str] = set()

    for item in existing_items:
        if not isinstance(item, dict):
            continue
        merged_item = dict(item)
        merged.append(merged_item)
        db_track_id = _playlist_item_db_track_id(
            merged_item,
            old_tid_to_db_track_id,
        )
        if db_track_id:
            seen_db_track_ids.add(db_track_id)
        source_path = merged_item.get("source_path") or merged_item.get("_source_path")
        if source_path:
            seen_source_paths.add(_import_source_path_key(source_path))

    for item in imported_items:
        if not isinstance(item, dict):
            continue
        source_path = item.get("source_path") or item.get("_source_path")
        source_key = _import_source_path_key(source_path)
        db_track_id = source_path_to_db_track_id.get(source_key, 0)
        if db_track_id and db_track_id in seen_db_track_ids:
            continue
        if source_key and source_key in seen_source_paths:
            continue
        merged.append(dict(item))
        if db_track_id:
            seen_db_track_ids.add(db_track_id)
        if source_key:
            seen_source_paths.add(source_key)

    return merged


def _merge_imported_playlist_with_existing(
    playlist: dict,
    existing_playlists: Iterable[dict],
    *,
    source_path_to_db_track_id: dict[str, int],
    tracks: Iterable[dict],
) -> dict:
    target_playlist = _find_import_target_playlist(
        existing_playlists,
        str(playlist.get("Title") or ""),
    )
    if target_playlist is None:
        return playlist

    merged = dict(target_playlist)
    merged.setdefault("_mhsd_dataset_type", 2)
    merged.setdefault("_mhsd_result_key", "mhlp")
    merged["_isNew"] = False
    merged["items"] = _merged_playlist_source_items(
        target_playlist.get("items", []),
        playlist.get("items", []),
        source_path_to_db_track_id=source_path_to_db_track_id,
        tracks=tracks,
    )
    merged["mhip_child_count"] = len(merged["items"])
    return merged


def build_backup_device_context(
    ipod_path: str,
    device_info: Any | None,
    *,
    device_name: str = "",
) -> BackupDeviceContext:
    """Return the sanitized backup identity for a connected device."""

    from iopenpod.sync.backup_manager import (
        BackupManager,
        get_device_display_name,
        get_device_identifier,
    )

    raw_id = get_device_identifier(ipod_path, device_info)
    return BackupDeviceContext(
        device_id=BackupManager._sanitize_id(raw_id),
        device_name=device_name.strip() or get_device_display_name(device_info),
        device_meta=build_backup_device_meta(device_info),
    )


def list_backup_devices_for_view(
    backup_dir: str,
    *,
    connected_ipod_path: str = "",
    connected_ipod_info: Any | None = None,
    connected_device_name: str = "",
) -> BackupDeviceInventory:
    """Return backup devices sorted for the backup browser sidebar."""

    from iopenpod.sync.backup_manager import BackupManager

    connected_context: BackupDeviceContext | None = None
    if connected_ipod_path:
        connected_context = build_backup_device_context(
            connected_ipod_path,
            connected_ipod_info,
            device_name=connected_device_name,
        )
        BackupManager(
            device_id=connected_context.device_id,
            backup_dir=backup_dir,
            device_name=connected_context.device_name,
            device_meta=connected_context.device_meta,
        ).update_device_metadata()

    devices_by_id = {
        item["device_id"]: dict(item)
        for item in BackupManager.list_all_devices(backup_dir)
    }
    connected_device_id = ""
    device_connected = bool(connected_ipod_path)

    if connected_context:
        connected_device_id = connected_context.device_id
        connected_info = devices_by_id.get(connected_device_id, {})
        connected_info.update(
            {
                "device_id": connected_device_id,
                "device_name": connected_context.device_name,
                "snapshot_count": int(
                    connected_info.get("snapshot_count", 0) or 0
                ),
                "device_meta": (
                    connected_context.device_meta
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

    from iopenpod.sync.backup_manager import BackupManager

    manager = BackupManager(device_id=device_id, backup_dir=backup_dir)
    return BackupSnapshotCatalog(
        snapshots=manager.list_snapshots(),
        total_backup_size=manager.get_backup_size(),
    )


def ensure_backup_folder(backup_dir: str, device_id: str = "") -> Path:
    """Create and return the backup folder, preferring a device subfolder."""

    from iopenpod.sync.backup_manager import _DEFAULT_BACKUP_DIR

    folder = Path(backup_dir or _DEFAULT_BACKUP_DIR)
    if device_id:
        device_folder = folder / device_id
        if device_folder.exists():
            folder = device_folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def delete_backup_snapshot(device_id: str, backup_dir: str, snapshot_id: str) -> bool:
    """Delete a backup snapshot for one device."""

    from iopenpod.sync.backup_manager import BackupManager

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
            from iopenpod.sync.backup_manager import BackupManager

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
            from iopenpod.sync.backup_manager import BackupManager

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
    selected_playlist_paths: frozenset[str] | None = None
    existing_playlists: tuple[dict, ...] = ()
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
        folders = tuple(
            path
            for path in request.pc_folders
            if path is not None and not (isinstance(path, str) and not path.strip())
        )
        if folders:
            return folders
        return (request.pc_folder,) if request.pc_folder else ()

    def run(self) -> None:
        try:
            from iopenpod.sync.core import (
                EngineOperation,
                EngineOptions,
                EngineRequest,
                SyncEngine,
            )

            request = self._request

            def on_engine_progress(progress) -> None:
                legacy = progress.legacy_event
                if isinstance(legacy, tuple) and len(legacy) == 4:
                    stage, cur, total, message = legacy
                    self.progress.emit(stage, cur, total, message)
                    return
                self.progress.emit(
                    str(progress.stage),
                    progress.current,
                    progress.total,
                    progress.message,
                )

            engine_request = EngineRequest(
                operation=EngineOperation.PLAN,
                ipod_path=request.ipod_path,
                pc_folders=self._pc_folders(request),
                ipod_tracks=tuple(request.ipod_tracks),
                existing_playlists=tuple(request.existing_playlists),
                track_edits=request.track_edits,
                photo_edits=request.photo_edits,
                options=EngineOptions(
                    supports_video=request.supports_video,
                    supports_podcast=request.supports_podcast,
                    supports_photo=request.supports_photo,
                    sync_workers=request.sync_workers,
                    rating_strategy=request.rating_strategy,
                    allowed_paths=request.allowed_paths,
                    selected_playlist_paths=request.selected_playlist_paths,
                    fpcalc_path=request.fpcalc_path,
                    photo_sync_settings=request.photo_sync_settings,
                    transcode_options=request.transcode_options,
                ),
                progress_callback=on_engine_progress,
                is_cancelled=self.isInterruptionRequested,
            )
            plan = SyncEngine().compute_plan(engine_request)

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
        from iopenpod.sync.unknown_metadata import UnknownMetadataRegistry
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
            from iopenpod.sync._formats import MEDIA_EXTENSIONS
            from iopenpod.sync.audio_fingerprint import get_or_compute_fingerprint_with_status
            from iopenpod.sync.ipod_track_paths import existing_ipod_track_file_path
            from iopenpod.sync.pc_library import PCLibrary

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
            pc_tracks = list(
                pc_library.scan(
                    include_video=True,
                    is_cancelled=self.isInterruptionRequested,
                )
            )
            if self.isInterruptionRequested():
                return
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
                fingerprint, _fingerprint_status = get_or_compute_fingerprint_with_status(
                    path,
                    write_to_file=False,
                )
                return fingerprint

            pool = ThreadPoolExecutor(max_workers=workers)
            cancel_fingerprints = False
            try:
                futures = {
                    pool.submit(_fp_pc, track.path): track
                    for track in pc_tracks
                }
                done = 0
                for fut in as_completed(futures):
                    if self.isInterruptionRequested():
                        cancel_fingerprints = True
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
            finally:
                pool.shutdown(
                    wait=not cancel_fingerprints,
                    cancel_futures=cancel_fingerprints,
                )

            ipod_candidates: list[tuple[dict, Path]] = []
            unresolved_ipod_tracks = 0
            unsupported_ipod_tracks = 0
            for track in request.ipod_tracks:
                location = track.get("Location")
                if not location:
                    unresolved_ipod_tracks += 1
                    continue
                ipod_file = existing_ipod_track_file_path(
                    self._request.ipod_path,
                    track,
                )
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
                    fp, _fingerprint_status = get_or_compute_fingerprint_with_status(
                        ipod_file,
                        write_to_file=False,
                    )
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
        from iopenpod.sync.unknown_metadata import apply_unknown_placeholders_to_mapping

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
        from iopenpod.sync.unknown_metadata import apply_unknown_placeholders_to_mapping

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
                from iopenpod.device import has_virtual_ipod_info

                is_virtual = has_virtual_ipod_info(path)
            except Exception:
                is_virtual = False
            if (
                not is_virtual
                and (not os.path.isdir(ipod_control) or not os.path.isdir(itunes_folder))
            ):
                self.not_found.emit(path)
                return

            from iopenpod.device import identify_ipod_at_path

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
        from iopenpod.device import scan_for_ipods

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
            from iopenpod.device.eject import eject_ipod

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
    track_edits_getter = getattr(cache, "get_track_edits", None)
    track_edits = (
        cast(Mapping[Any, Mapping[str, Any]], track_edits_getter())
        if callable(track_edits_getter)
        else {}
    )
    if track_edits:
        tracks_by_db_track_id = {
            _track_db_track_id(track): track
            for track in tracks
            if _track_db_track_id(track)
        }
        for raw_db_track_id, edits in track_edits.items():
            try:
                db_track_id = int(raw_db_track_id)
            except (TypeError, ValueError):
                continue
            track = tracks_by_db_track_id.get(db_track_id)
            if track is None:
                continue
            for field, change in edits.items():
                if isinstance(change, tuple) and len(change) >= 2:
                    track[field] = change[1]
                else:
                    track[field] = change
    artwork_sources = copy.deepcopy(cache.get_track_artwork_edits())
    for track in tracks:
        track.pop("_iop_pending_artwork_path", None)
    playlists = copy.deepcopy(cache.get_playlists())
    return tracks, playlists, artwork_sources


def _engine_quick_write(
    ipod_path: str,
    *,
    tracks_data: list[dict[str, Any]],
    playlists_data: list[dict[str, Any]],
    artwork_sources: dict[int, str],
):
    from iopenpod.sync.core import (
        EngineOperation,
        EngineRequest,
        SyncEngine,
    )

    return SyncEngine().quick_write(
        EngineRequest(
            operation=EngineOperation.QUICK_WRITE,
            ipod_path=ipod_path,
            tracks_data=tuple(tracks_data),
            playlists_data=tuple(playlists_data),
            artwork_sources=artwork_sources,
        )
    )


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
            result = _engine_quick_write(
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
            result = _engine_quick_write(
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
            result = _engine_quick_write(
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
            from iopenpod.sync.audio_fingerprint import get_or_compute_fingerprint_with_status
            from iopenpod.sync.contracts import (
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from iopenpod.sync.core import EngineOperation, EngineRequest, SyncEngine
            from iopenpod.sync.mapping import MappingManager
            from iopenpod.sync.pc_library import PCLibrary
            from iopenpod.sync.playlist_parser import (
                PlaylistPathResolver,
                parse_playlist,
            )

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
            resolver = PlaylistPathResolver()
            for raw_path in raw_paths:
                resolved_path = resolver.resolve_existing_path(raw_path)
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
            from iopenpod.sync._db_io import read_existing_database
            from iopenpod.sync.existing_track_matcher import (
                existing_track_match_db_track_id,
            )

            fresh_db = read_existing_database(ipod_root)
            fresh_tracks = list(fresh_db.get("tracks", []))

            playlist_db_track_ids: list[int] = []
            needs_fingerprint: list[str] = []
            already_present_db_track_ids: list[int] = []

            for idx, raw_path in enumerate(existing_paths):
                path = Path(raw_path)
                needs_fingerprint.append(raw_path)
                self.progress.emit(idx + 1, total, f"Needs ID check: {path.name}")

            to_add: list[SyncItem] = []
            if needs_fingerprint:
                mapping = MappingManager(self._ipod_path).load()
                valid_db_track_ids = {
                    db_track_id
                    for track in fresh_tracks
                    if (db_track_id := _track_db_track_id(track))
                }
                ipod_fingerprint_cache: dict[str, str | None] = {}
                fingerprint_total = len(needs_fingerprint)

                for idx, raw_path in enumerate(needs_fingerprint):
                    path = Path(raw_path)
                    global_idx = idx + 1
                    self.progress.emit(
                        global_idx,
                        total,
                        (
                            f"Identifying ({idx + 1} of {fingerprint_total}): "
                            f"{path.name}"
                        ),
                    )

                    fingerprint, _fingerprint_status = (
                        get_or_compute_fingerprint_with_status(
                            raw_path,
                            fpcalc_path=self._fpcalc_path,
                            write_to_file=False,
                        )
                    )
                    if fingerprint is None:
                        skipped += 1
                        continue

                    library = PCLibrary(str(path.parent))
                    pc_track = library._read_track(path)
                    if pc_track is None:
                        skipped += 1
                        continue

                    if fresh_tracks:
                        self.progress.emit(
                            global_idx,
                            total,
                            "Checking existing iPod candidates...",
                        )
                    existing_db_track_id = existing_track_match_db_track_id(
                        ipod_root,
                        fresh_tracks,
                        pc_track,
                        path,
                        fingerprint,
                        mapping=mapping,
                        valid_db_track_ids=valid_db_track_ids,
                        fpcalc_path=self._fpcalc_path,
                        fingerprint_cache=ipod_fingerprint_cache,
                    )

                    if existing_db_track_id:
                        already_present_db_track_ids.append(existing_db_track_id)
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
                request = EngineRequest(
                    operation=EngineOperation.EXECUTE,
                    ipod_path=self._ipod_path,
                    plan=plan,
                    mapping=fresh_mapping,
                    progress_callback=_on_sync_progress,
                )
                result = SyncEngine().execute_plan(request)
                if not result.success:
                    error = result.errors[0] if result.errors else "Unknown error"
                    self.failed.emit(f"Sync failed: {error}")
                    return

            if to_add:
                self.progress.emit(0, 0, "Resolving track IDs...")
                final_mapping = MappingManager(self._ipod_path).load()

                for item in to_add:
                    if item.fingerprint is None:
                        continue
                    entries = final_mapping.get_entries(item.fingerprint)
                    if entries:
                        playlist_db_track_ids.append(entries[0].db_track_id)

            playlist_db_track_ids.extend(already_present_db_track_ids)

            if not playlist_db_track_ids:
                self.failed.emit("No tracks could be matched to iPod database IDs.")
                return

            self.progress.emit(0, 0, f"Writing playlist '{playlist_name}'...")

            target_playlist = _find_import_target_playlist(
                self._cache.get_playlists(),
                playlist_name,
            )
            playlist_items = _merged_playlist_items(
                target_playlist.get("items", []) if target_playlist else [],
                playlist_db_track_ids,
                fresh_tracks,
            )
            if not playlist_items:
                self.failed.emit("No tracks could be mapped to iPod database IDs.")
                return

            if target_playlist:
                playlist = dict(target_playlist)
                playlist.setdefault("_mhsd_dataset_type", 2)
                playlist.setdefault("_mhsd_result_key", "mhlp")
                playlist["_isNew"] = False
                playlist["items"] = playlist_items
                playlist["mhip_child_count"] = len(playlist_items)
            else:
                playlist_id = random.getrandbits(64)
                playlist = {
                    "Title": playlist_name,
                    "playlist_id": playlist_id,
                    "_isNew": True,
                    "_source": "regular",
                    "items": playlist_items,
                    "mhip_child_count": len(playlist_items),
                }
            self._cache.save_user_playlist(playlist)
            cache_mutated = True

            tracks_data, playlists_data, artwork_sources = (
                _snapshot_cache_for_itunesdb_write(self._cache)
            )
            if to_add:
                fresh_db = read_existing_database(Path(self._ipod_path))
                tracks_data = copy.deepcopy(fresh_db.get("tracks", []))
                playlists_data = copy.deepcopy(self._cache.get_playlists())
            elif already_present_db_track_ids:
                tracks_data = copy.deepcopy(fresh_tracks)
                playlists_data = copy.deepcopy(self._cache.get_playlists())
            write_result = _engine_quick_write(
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
                len(already_present_db_track_ids),
                skipped,
            )
        except Exception as exc:
            logger.exception("PlaylistImportWorker failed")
            if cache_mutated:
                _reload_after_itunesdb_write(self._cache)
            self.failed.emit(str(exc))


def _delete_imported_otg_files(ipod_path: str) -> None:
    try:
        from iopenpod.itunesdb_parser.otg import delete_otg_files

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
        backup_device_name: str = "",
        device_info: DeviceIdentitySnapshot | None = None,
        device_capabilities: DeviceCapabilitySnapshot | None = None,
        on_sync_complete: Callable[[], None] | None = None,
        sync_until_full: bool = False,
    ):
        super().__init__()
        self.ipod_path = ipod_path
        self.plan = plan
        self.skip_backup = skip_backup
        self._skip_backup_requested = False
        self.backup_device_name = backup_device_name
        self.settings = settings
        self.device_info = device_info
        self.device_capabilities = device_capabilities
        self.on_sync_complete = on_sync_complete
        self.sync_until_full = bool(sync_until_full)
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
        """Signal the worker to stop retrying the active scrobbling service."""
        self._give_up_scrobble_requested = True

    def run(self) -> None:
        try:
            from iopenpod.sync.contracts import SyncProgress
            from iopenpod.sync.core import (
                EngineOperation,
                EngineOptions,
                EngineRequest,
                SyncEngine,
            )
            from iopenpod.sync.mapping import MappingManager

            settings = self.settings
            tools = check_sync_tool_availability(settings)
            if tools.has_missing:
                raise RuntimeError(
                    f"{tools.tool_list} required before sync.\n\n"
                    f"{tools.install_help_text}"
                )

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

            if getattr(self.plan, "mapping", None) is not None:
                mapping = self.plan.mapping
            else:
                mapping_manager = MappingManager(self.ipod_path)
                mapping = mapping_manager.load()

            def on_engine_progress(progress) -> None:
                legacy = progress.legacy_event
                if legacy is not None:
                    self.progress.emit(legacy)
                    return
                self.progress.emit(
                    SyncProgress(
                        str(progress.stage),
                        progress.current,
                        progress.total,
                        message=progress.message,
                    )
                )

            engine_request = EngineRequest(
                operation=EngineOperation.EXECUTE,
                ipod_path=self.ipod_path,
                plan=self.plan,
                mapping=mapping,
                options=EngineOptions(
                    sync_workers=settings.sync_workers,
                    device_write_workers=settings.device_write_workers,
                    fpcalc_path=settings.fpcalc_path,
                    transcode_options=build_transcode_options(settings),
                    transcode_cache_dir=settings.transcode_cache_dir or "",
                    max_cache_size_gb=settings.max_cache_size_gb,
                    dry_run=False,
                    write_back_to_pc=settings.write_back_to_pc,
                    compute_sound_check=settings.compute_sound_check,
                    scrobble_on_sync=settings.scrobble_on_sync,
                    listenbrainz_token=settings.listenbrainz_token or "",
                    listenbrainz_username=settings.listenbrainz_username or "",
                    lastfm_api_key=getattr(settings, "lastfm_api_key", ""),
                    lastfm_api_secret=getattr(settings, "lastfm_api_secret", ""),
                    lastfm_session_key=getattr(settings, "lastfm_session_key", ""),
                    lastfm_username=getattr(settings, "lastfm_username", ""),
                    sync_until_full=self.sync_until_full,
                    photo_sync_settings={
                        "rotate_tall_photos_for_device": (
                            settings.rotate_tall_photos_for_device
                        ),
                        "fit_photo_thumbnails": settings.fit_photo_thumbnails,
                    },
                ),
                device_info=self.device_info,
                device_capabilities=self.device_capabilities,
                progress_callback=on_engine_progress,
                is_cancelled=self.isInterruptionRequested,
                on_sync_complete=self.on_sync_complete,
                is_scrobble_cancelled=lambda: self._give_up_scrobble_requested,
                on_cancel_with_partial=_on_cancel_with_partial,
            )

            self.finished.emit(SyncEngine().execute_plan(engine_request))
        except Exception as exc:
            logger.exception("SyncExecuteWorker failed")
            self.error.emit(str(exc))

    def _create_presync_backup(self, settings: AppSettings, progress_type) -> None:
        try:
            self.progress.emit(
                progress_type("backup", 0, 0, message="Creating pre-sync backup...")
            )
            from iopenpod.sync.backup_manager import (
                BackupManager,
                get_device_display_name,
                get_device_identifier,
            )

            device_id = get_device_identifier(self.ipod_path, self.device_info)
            device_name = (
                self.backup_device_name.strip()
                or get_device_display_name(self.device_info)
            )
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
            from iopenpod.sync.capability_filter import is_track_supported_by_device
            from iopenpod.sync.contracts import (
                StorageSummary,
                SyncAction,
                SyncItem,
                SyncPlan,
            )
            from iopenpod.sync.existing_track_matcher import (
                existing_track_match_db_track_id,
            )
            from iopenpod.sync.pc_library import PCLibrary

            items: list[SyncItem] = []
            total_bytes = 0
            fresh_db: dict[str, Any] = {}
            fresh_tracks: list[dict] = []
            existing_standard_playlists: list[dict] = []
            mapping: Any | None = None
            valid_db_track_ids: set[int] = set()
            ipod_fingerprint_cache: dict[str, str | None] = {}
            source_path_to_db_track_id: dict[str, int] = {}
            matched_pc_paths: dict[int, str] = {}
            if self._ipod_path:
                try:
                    from iopenpod.sync._db_io import read_existing_database
                    from iopenpod.sync.mapping import MappingManager

                    fresh_db = read_existing_database(Path(self._ipod_path))
                    fresh_tracks = list(fresh_db.get("tracks", []))
                    existing_standard_playlists = _fresh_standard_playlists(fresh_db)
                    valid_db_track_ids = {
                        db_track_id
                        for track in fresh_tracks
                        if (db_track_id := _track_db_track_id(track))
                    }
                    mapping = MappingManager(self._ipod_path).load()
                except Exception as exc:
                    logger.debug("Could not load iPod state for dropped files: %s", exc)

            playlist_media_paths, playlists_to_add = build_dropped_playlist_imports(
                self._playlist_paths,
                include_video=self._supports_video,
            )
            media_paths: list[Path] = []
            seen_media: set[str] = set()
            for path in (*self._file_paths, *playlist_media_paths):
                append_unique_path(media_paths, seen_media, path)

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
                        fingerprint = None
                        existing_db_track_id = 0
                        if mapping is not None and fresh_tracks:
                            try:
                                from iopenpod.sync.audio_fingerprint import (
                                    get_or_compute_fingerprint_with_status,
                                )

                                fingerprint, _fingerprint_status = (
                                    get_or_compute_fingerprint_with_status(
                                        path,
                                        write_to_file=False,
                                    )
                                )
                            except Exception as exc:
                                logger.debug(
                                    "Could not fingerprint dropped file %s: %s",
                                    path,
                                    exc,
                            )
                            if fingerprint:
                                existing_db_track_id = existing_track_match_db_track_id(
                                    Path(self._ipod_path),
                                    fresh_tracks,
                                    track,
                                    path,
                                    fingerprint,
                                    mapping=mapping,
                                    valid_db_track_ids=valid_db_track_ids,
                                    fpcalc_path=None,
                                    fingerprint_cache=ipod_fingerprint_cache,
                                )
                        if existing_db_track_id:
                            source_key = _import_source_path_key(path)
                            source_path_to_db_track_id[source_key] = existing_db_track_id
                            matched_pc_paths[existing_db_track_id] = str(path)
                            continue
                        items.append(
                            SyncItem(
                                action=SyncAction.ADD_TO_IPOD,
                                fingerprint=fingerprint,
                                pc_track=track,
                                description=f"{track.artist} - {track.title}",
                            )
                        )
                        total_bytes += track.size
                except Exception as exc:
                    logger.warning("Failed to read dropped file %s: %s", path, exc)

            plan = SyncPlan()
            plan.to_add.extend(items)
            plan.matched_pc_paths.update(matched_pc_paths)
            playlist_updates = [
                _merge_imported_playlist_with_existing(
                    playlist,
                    existing_standard_playlists,
                    source_path_to_db_track_id=source_path_to_db_track_id,
                    tracks=fresh_tracks,
                )
                for playlist in playlists_to_add
            ]
            plan.playlists_to_add.extend(
                playlist for playlist in playlist_updates if playlist.get("_isNew", True)
            )
            plan.playlists_to_edit.extend(
                playlist for playlist in playlist_updates if not playlist.get("_isNew", True)
            )
            plan.storage = StorageSummary(bytes_to_add=total_bytes)
            if (
                self._supports_photo
                and self._photo_imports
                and self._ipod_path
            ):
                from iopenpod.sync.photos import (
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
