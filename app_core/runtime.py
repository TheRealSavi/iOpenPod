"""Runtime state owners and background helpers extracted from the GUI shell."""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, pyqtSignal, pyqtSlot

from .services import DeviceInfoLike, LibraryCacheLike

logger = logging.getLogger(__name__)


def _is_music_browser_track(track: dict) -> bool:
    """Return whether a track belongs in the music browser indexes."""

    try:
        media_type = int(track.get("media_type", 1) or 0)
    except (TypeError, ValueError):
        media_type = 1
    return media_type == 0 or bool(media_type & 0x01)


def _build_track_indexes(
    tracks: list[dict],
) -> tuple[dict, dict, dict, dict, dict]:
    album_index = {}
    album_only_index = {}
    artist_index = {}
    genre_index = {}
    track_id_index = {}

    for track in tracks:
        track_id = track.get("track_id")
        if track_id is not None:
            track_id_index[track_id] = track

        if not _is_music_browser_track(track):
            continue

        album = track.get("Album", "Unknown Album")
        artist = track.get("Artist", "Unknown Artist")
        album_artist = track.get("Album Artist") or artist
        genre = track.get("Genre", "Unknown Genre")

        album_key = (album, album_artist)
        album_index.setdefault(album_key, []).append(track)
        album_only_index.setdefault(album, []).append(track)
        artist_index.setdefault(artist, []).append(track)
        genre_index.setdefault(genre, []).append(track)

    return album_index, album_only_index, artist_index, genre_index, track_id_index


def same_device_path(left: str | None, right: str | None) -> bool:
    """Compare device paths using platform-normalized absolute paths."""

    if not left or not right:
        return not left and not right
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


class CancellationToken:
    """Thread-safe cancellation token for workers."""

    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def reset(self) -> None:
        self._cancelled.clear()


class ThreadPoolSingleton:
    """Shared thread pool for application background work."""

    _instance: QThreadPool | None = None

    @classmethod
    def get_instance(cls) -> QThreadPool:
        if cls._instance is None:
            cls._instance = QThreadPool.globalInstance()
        assert cls._instance is not None
        return cls._instance


class WorkerSignals(QObject):
    """Signal set shared by generic background workers."""

    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)


class Worker(QRunnable):
    """Generic background worker with error recovery."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancellation_token = DeviceManager.get_instance().cancellation_token
        self._is_cancelled = False
        self._fn_name = getattr(fn, "__name__", str(fn))

    def is_cancelled(self) -> bool:
        return self._is_cancelled or self._cancellation_token.is_cancelled()

    def cancel(self) -> None:
        self._is_cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        if self.is_cancelled():
            logger.debug("Worker %s cancelled before start", self._fn_name)
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
            return

        try:
            result = self.fn(*self.args, **self.kwargs)
            if not self.is_cancelled():
                try:
                    self.signals.result.emit(result)
                except RuntimeError:
                    logger.debug(
                        "Worker %s result signal receiver deleted", self._fn_name
                    )
        except Exception as exc:
            if not self.is_cancelled():
                logger.error("Worker %s failed: %s", self._fn_name, exc, exc_info=True)
                exc_type, value = sys.exc_info()[:2]
                try:
                    self.signals.error.emit((exc_type, value, traceback.format_exc()))
                except RuntimeError:
                    logger.debug(
                        "Worker %s error signal receiver deleted", self._fn_name
                    )
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class DeviceSettingsLoader(QThread):
    """Load per-device settings from the iPod without blocking Qt."""

    loaded = pyqtSignal(int, str, str, object)
    failed = pyqtSignal(int, str, str, str)

    def __init__(self, token: int, ipod_root: str, device_key: str):
        super().__init__()
        self._token = token
        self._ipod_root = ipod_root
        self._device_key = device_key

    def run(self) -> None:
        try:
            from infrastructure.settings_runtime import get_default_runtime

            settings_runtime = get_default_runtime()
            state = settings_runtime.load_device_settings(
                self._ipod_root,
                self._device_key,
                settings_runtime.get_global_settings(),
            )
            if not self.isInterruptionRequested():
                self.loaded.emit(
                    self._token,
                    self._ipod_root,
                    self._device_key,
                    state,
                )
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(
                    self._token,
                    self._ipod_root,
                    self._device_key,
                    str(exc),
                )


class DeviceManager(QObject):
    """Manages the currently selected iPod device path."""

    device_changed = pyqtSignal(str)
    device_changing = pyqtSignal()
    device_settings_loaded = pyqtSignal(str)
    device_settings_failed = pyqtSignal(str, str)

    _instance = None

    def __init__(self):
        super().__init__()
        self._device_path = None
        self._discovered_ipod = None
        self._cancellation_token = CancellationToken()
        self._settings_load_token = 0
        self._device_settings_loading = False
        self._device_settings_workers: list[DeviceSettingsLoader] = []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = DeviceManager()
        return cls._instance

    @property
    def cancellation_token(self) -> CancellationToken:
        return self._cancellation_token

    @property
    def device_settings_loading(self) -> bool:
        return self._device_settings_loading

    def cancel_all_operations(self) -> None:
        self._cancellation_token.cancel()
        self._cancellation_token = CancellationToken()

    @property
    def device_path(self) -> str | None:
        return self._device_path

    @property
    def discovered_ipod(self) -> DeviceInfoLike | None:
        return self._discovered_ipod

    @discovered_ipod.setter
    def discovered_ipod(self, ipod: DeviceInfoLike | None) -> None:
        self._discovered_ipod = ipod
        self._sync_device_info(ipod)

    @staticmethod
    def _same_device_path(left: str | None, right: str | None) -> bool:
        return same_device_path(left, right)

    def _cancel_device_settings_loads(self) -> None:
        self._settings_load_token += 1
        self._device_settings_loading = False
        for worker in list(self._device_settings_workers):
            worker.requestInterruption()

    def _forget_device_settings_worker(self, worker: DeviceSettingsLoader) -> None:
        try:
            self._device_settings_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def _start_device_settings_load(self, path: str, key: str) -> None:
        self._settings_load_token += 1
        token = self._settings_load_token
        self._device_settings_loading = True
        worker = DeviceSettingsLoader(token, path, key)
        self._device_settings_workers.append(worker)
        worker.loaded.connect(self._on_device_settings_loaded)
        worker.failed.connect(self._on_device_settings_failed)
        worker.finished.connect(lambda w=worker: self._forget_device_settings_worker(w))
        worker.start()

    @pyqtSlot(int, str, str, object)
    def _on_device_settings_loaded(
        self, token: int, path: str, key: str, state
    ) -> None:
        if token != self._settings_load_token or not self._same_device_path(
            path, self._device_path
        ):
            return
        try:
            from infrastructure.settings_runtime import get_default_runtime

            get_default_runtime().apply_loaded_device_settings(path, key, state)
            self._device_settings_loading = False
            logger.info("Device settings loaded for %s", path)
            self.device_settings_loaded.emit(path)
        except Exception:
            logger.warning("Failed to activate loaded device settings", exc_info=True)
            self._device_settings_loading = False
            self.device_settings_failed.emit(path, "Failed to activate device settings")

    @pyqtSlot(int, str, str, str)
    def _on_device_settings_failed(
        self, token: int, path: str, _key: str, error: str
    ) -> None:
        if token != self._settings_load_token or not self._same_device_path(
            path, self._device_path
        ):
            return
        self._device_settings_loading = False
        logger.warning("Failed to load device settings for %s: %s", path, error)
        self.device_settings_failed.emit(path, error)

    @device_path.setter
    def device_path(self, path: str | None) -> None:
        self.device_changing.emit()
        self.cancel_all_operations()
        iTunesDBCache.get_instance().clear()
        self._cancel_device_settings_loads()
        self._device_path = path
        if path is None:
            self._discovered_ipod = None
            from ipod_device import clear_current_device

            clear_current_device()
        try:
            from infrastructure.settings_runtime import (
                device_settings_key,
                get_default_runtime,
            )

            settings_runtime = get_default_runtime()
            settings_runtime.clear_device_settings()
            if path:
                self._start_device_settings_load(
                    path,
                    device_settings_key(path, self._discovered_ipod),
                )
        except Exception:
            self._device_settings_loading = False
            logger.warning("Failed to start device settings load", exc_info=True)
        self.device_changed.emit(path or "")

    @property
    def itunesdb_path(self) -> str | None:
        if not self._device_path:
            return None
        from ipod_device import resolve_itdb_path

        return resolve_itdb_path(self._device_path)

    @property
    def artworkdb_path(self) -> str | None:
        if not self._device_path:
            return None
        return os.path.join(self._device_path, "iPod_Control", "Artwork", "ArtworkDB")

    @property
    def artwork_folder_path(self) -> str | None:
        if not self._device_path:
            return None
        return os.path.join(self._device_path, "iPod_Control", "Artwork")

    def is_valid_ipod_root(self, path: str) -> bool:
        try:
            from ipod_device import has_virtual_ipod_info

            if has_virtual_ipod_info(path):
                return True
        except Exception:
            pass
        ipod_control = os.path.join(path, "iPod_Control")
        itunes_folder = os.path.join(ipod_control, "iTunes")
        return os.path.isdir(ipod_control) and os.path.isdir(itunes_folder)

    @staticmethod
    def _sync_device_info(ipod) -> None:
        from ipod_device import clear_current_device, set_current_device

        if ipod is None:
            clear_current_device()
            return
        set_current_device(ipod)


class iTunesDBCache(QObject):
    """Cache for parsed iTunesDB data. Loads once when device selected."""

    data_ready = pyqtSignal()
    _instance: iTunesDBCache | None = None

    playlists_changed = pyqtSignal()
    playlist_quick_sync = pyqtSignal()
    tracks_changed = pyqtSignal()
    photos_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._data: dict | None = None
        self._device_path: str | None = None
        self._is_loading: bool = False
        self._lock = threading.Lock()
        self._album_index: dict | None = None
        self._album_only_index: dict | None = None
        self._artist_index: dict | None = None
        self._genre_index: dict | None = None
        self._track_id_index: dict | None = None
        self._photo_db = None
        self._user_playlists: list[dict] = []
        self._track_edits: dict[int, dict[str, tuple]] = {}
        from SyncEngine.photos import PhotoEditState

        self._photo_edits = PhotoEditState()

    @classmethod
    def get_instance(cls) -> iTunesDBCache:
        if cls._instance is None:
            cls._instance = iTunesDBCache()
        return cls._instance

    def clear(self) -> None:
        with self._lock:
            self._data = None
            self._device_path = None
            self._is_loading = False
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None
            self._photo_db = None
            self._user_playlists.clear()
            self._track_edits.clear()
            from SyncEngine.photos import PhotoEditState

            self._photo_edits = PhotoEditState()

    def invalidate(self) -> None:
        with self._lock:
            self._data = None
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None

    def is_ready(self) -> bool:
        device = DeviceManager.get_instance()
        with self._lock:
            return (
                self._data is not None
                and self._device_path == device.device_path
                and not self._is_loading
            )

    def is_loading(self) -> bool:
        with self._lock:
            return self._is_loading

    @property
    def device_path(self) -> str | None:
        with self._lock:
            return self._device_path

    def get_data(self) -> dict | None:
        device = DeviceManager.get_instance()
        with self._lock:
            if self._data is not None and self._device_path == device.device_path:
                return self._data
            return None

    def get_tracks(self) -> list:
        data = self.get_data()
        return list(data.get("mhlt", [])) if data else []

    def get_albums(self) -> list:
        data = self.get_data()
        return list(data.get("mhla", [])) if data else []

    def get_photo_db(self):
        data = self.get_data()
        return data.get("photodb") if data else None

    def replace_photo_db(self, photodb) -> None:
        with self._lock:
            self._photo_db = photodb
            if self._data is not None:
                self._data["photodb"] = photodb
        self.photos_changed.emit()

    def get_album_index(self) -> dict:
        with self._lock:
            return self._album_index or {}

    def get_album_only_index(self) -> dict:
        with self._lock:
            return self._album_only_index or {}

    def get_artist_index(self) -> dict:
        with self._lock:
            return self._artist_index or {}

    def get_genre_index(self) -> dict:
        with self._lock:
            return self._genre_index or {}

    def get_track_id_index(self) -> dict:
        with self._lock:
            return self._track_id_index or {}

    def get_playlists(self) -> list:
        data = self.get_data()
        if not data:
            return []

        seen_ids: set[int] = set()
        result: list[dict] = []

        has_type2_master = False
        for playlist in data.get("mhlp", []):
            playlist = {**playlist, "_source": "regular"}
            playlist_id = playlist.get("playlist_id", 0)
            if playlist_id not in seen_ids:
                seen_ids.add(playlist_id)
                result.append(playlist)
                if playlist.get("master_flag"):
                    has_type2_master = True

        for playlist in data.get("mhlp_podcast", []):
            playlist_id = playlist.get("playlist_id", 0)
            if playlist_id in seen_ids:
                continue
            source = (
                "podcast" if playlist.get("podcast_flag", 0) == 1 else "regular"
            )
            playlist = {**playlist, "_source": source}
            if has_type2_master:
                playlist["master_flag"] = 0
            seen_ids.add(playlist_id)
            result.append(playlist)

        for playlist in data.get("mhlp_smart", []):
            playlist_id = playlist.get("playlist_id", 0)
            if playlist_id in seen_ids:
                continue
            playlist = {**playlist, "_source": "smart", "master_flag": 0}
            seen_ids.add(playlist_id)
            result.append(playlist)

        with self._lock:
            for user_playlist in self._user_playlists:
                playlist_id = user_playlist.get("playlist_id", 0)
                if playlist_id in seen_ids:
                    result = [
                        user_playlist
                        if row.get("playlist_id") == playlist_id
                        else row
                        for row in result
                    ]
                else:
                    seen_ids.add(playlist_id)
                    result.append(user_playlist)

        return result

    def save_user_playlist(self, playlist: dict) -> None:
        import random

        with self._lock:
            playlist_id = playlist.get("playlist_id", 0)
            if not playlist_id:
                playlist_id = random.getrandbits(64)
                playlist["playlist_id"] = playlist_id
            items = playlist.get("items")
            if isinstance(items, list):
                playlist["mhip_child_count"] = len(items)

            replaced = False
            for index, user_playlist in enumerate(self._user_playlists):
                if user_playlist.get("playlist_id") == playlist_id:
                    self._user_playlists[index] = playlist
                    replaced = True
                    break
            if not replaced:
                self._user_playlists.append(playlist)

        logger.info(
            "User playlist saved: '%s' (id=0x%016X, new=%s)",
            playlist.get("Title", "?"),
            playlist_id,
            not replaced,
        )
        self.playlists_changed.emit()

    def remove_user_playlist(self, playlist_id: int) -> bool:
        with self._lock:
            before = len(self._user_playlists)
            self._user_playlists = [
                playlist
                for playlist in self._user_playlists
                if playlist.get("playlist_id") != playlist_id
            ]
            removed = len(self._user_playlists) < before
        if removed:
            self.playlists_changed.emit()
        return removed

    def get_user_playlists(self) -> list[dict]:
        with self._lock:
            return list(self._user_playlists)

    def has_pending_playlists(self) -> bool:
        with self._lock:
            return len(self._user_playlists) > 0

    def clear_pending_playlists(self) -> None:
        with self._lock:
            self._user_playlists.clear()

    def commit_user_playlists(self) -> None:
        """Hydrate pending playlist edits into the live parsed cache in place."""
        with self._lock:
            if not self._user_playlists:
                return

            data = self._data
            if data is None:
                self._user_playlists.clear()
                return

            regular = data.setdefault("mhlp", [])
            podcast = data.setdefault("mhlp_podcast", [])
            smart = data.setdefault("mhlp_smart", [])
            buckets = (regular, podcast, smart)

            for pending in self._user_playlists:
                playlist_id = pending.get("playlist_id", 0)
                if not playlist_id or pending.get("master_flag"):
                    continue

                row = dict(pending)
                items = row.get("items")
                if isinstance(items, list):
                    row["mhip_child_count"] = len(items)

                if row.get("smart_playlist_data") or row.get("_source") == "smart":
                    target = smart
                elif row.get("podcast_flag", 0) == 1 or row.get("_source") == "podcast":
                    target = podcast
                else:
                    target = regular

                for bucket in buckets:
                    for index, existing in enumerate(bucket):
                        if existing.get("playlist_id") == playlist_id:
                            if bucket is target:
                                bucket[index] = row
                            else:
                                del bucket[index]
                            break
                    else:
                        continue
                    continue

                if not any(existing.get("playlist_id") == playlist_id for existing in target):
                    target.append(row)

            self._user_playlists.clear()

        self.playlists_changed.emit()

    def update_track_flags(self, tracks: list[dict], changes: dict) -> None:
        with self._lock:
            for track in tracks:
                db_track_id = track.get("db_track_id", track.get("db_id", 0))
                if not db_track_id:
                    continue
                edits = self._track_edits.setdefault(db_track_id, {})
                for key, value in changes.items():
                    if key in edits:
                        original, _ = edits[key]
                        edits[key] = (original, value)
                    else:
                        edits[key] = (track.get(key), value)
                    track[key] = value

            if self._data is not None:
                (
                    self._album_index,
                    self._album_only_index,
                    self._artist_index,
                    self._genre_index,
                    self._track_id_index,
                ) = _build_track_indexes(list(self._data.get("mhlt", [])))

        logger.info(
            "Track metadata updated on %d track(s): %s",
            len(tracks),
            ", ".join(f"{key}={value}" for key, value in changes.items()),
        )
        self.tracks_changed.emit()

    def get_track_edits(self) -> dict[int, dict[str, tuple]]:
        with self._lock:
            return dict(self._track_edits)

    def has_pending_track_edits(self) -> bool:
        with self._lock:
            return len(self._track_edits) > 0

    def clear_track_edits(self) -> None:
        with self._lock:
            self._track_edits.clear()

    def get_photo_edits(self):
        with self._lock:
            return self._photo_edits

    def clear_photo_edits(self) -> None:
        from SyncEngine.photos import PhotoEditState

        with self._lock:
            self._photo_edits = PhotoEditState()
        self.photos_changed.emit()

    def clear_pending_sync_state(self) -> None:
        self.clear_pending_playlists()
        self.clear_track_edits()
        self.clear_photo_edits()

    def has_pending_photo_edits(self) -> bool:
        with self._lock:
            return bool(self._photo_edits.has_changes)

    def stage_photo_import(self, source_path: str, album_name: str = "") -> None:
        with self._lock:
            self._photo_edits.imported_files.append((source_path, album_name))
        self.photos_changed.emit()

    def stage_photo_album_create(self, album_name: str) -> None:
        with self._lock:
            self._photo_edits.created_albums.add(album_name)
        self.photos_changed.emit()

    def stage_photo_album_rename(self, old_name: str, new_name: str) -> None:
        with self._lock:
            self._photo_edits.renamed_albums[old_name] = new_name
        self.photos_changed.emit()

    def stage_photo_album_delete(self, album_name: str) -> None:
        with self._lock:
            self._photo_edits.deleted_albums.add(album_name)
        self.photos_changed.emit()

    def stage_photo_membership_remove(self, visual_hash: str, album_name: str) -> None:
        with self._lock:
            self._photo_edits.membership_removals.add((visual_hash, album_name))
        self.photos_changed.emit()

    def stage_photo_delete(self, visual_hash: str) -> None:
        with self._lock:
            self._photo_edits.deleted_photos.add(visual_hash)
        self.photos_changed.emit()

    def pop_track_edits(self) -> dict[int, dict[str, tuple]]:
        with self._lock:
            edits = dict(self._track_edits)
            self._track_edits.clear()
            return edits

    def set_data(self, data: dict, device_path: str) -> None:
        tracks = list(data.get("mhlt", []))
        album_index, album_only_index, artist_index, genre_index, track_id_index = _build_track_indexes(tracks)

        with self._lock:
            self._data = data
            self._device_path = device_path
            self._is_loading = False
            self._album_index = album_index
            self._album_only_index = album_only_index
            self._artist_index = artist_index
            self._genre_index = genre_index
            self._track_id_index = track_id_index
            self._photo_db = data.get("photodb")
        self.data_ready.emit()

    def set_loading(self, loading: bool) -> None:
        with self._lock:
            self._is_loading = loading

    def start_loading(self) -> None:
        device = DeviceManager.get_instance()
        if not device.device_path:
            return

        with self._lock:
            if self._is_loading:
                return
            if self._data is not None and self._device_path == device.device_path:
                self.data_ready.emit()
                return
            self._is_loading = True

        worker = Worker(self._load_data, device.device_path, device.itunesdb_path)
        worker.signals.result.connect(self._on_load_complete)
        worker.signals.error.connect(self._on_load_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _load_data(self, device_path: str, itunesdb_path: str | None) -> tuple:
        data: dict = {}
        if not itunesdb_path:
            logger.warning("No iTunesDB path available for device: %s", device_path)
            return data, device_path

        try:
            from iTunesDB_Parser.ipod_library import load_ipod_library

            parsed = load_ipod_library(itunesdb_path) or {}
            if isinstance(parsed, dict):
                data = parsed
            else:
                logger.warning(
                    "iTunesDB parser returned unexpected type: %s",
                    type(parsed).__name__,
                )
        except Exception:
            logger.exception("Failed to load iTunesDB for device: %s", device_path)

        try:
            from SyncEngine.photos import PhotoDB, read_photo_db

            data["photodb"] = read_photo_db(device_path)
        except Exception:
            logger.exception(
                "Failed to load photo database for device: %s",
                device_path,
            )
            from SyncEngine.photos import PhotoDB

            data["photodb"] = PhotoDB()

        return (data, device_path)

    def _on_load_error(self, error: tuple) -> None:
        exc_type, value, _traceback = error
        logger.error(
            "Device load worker failed: %s: %s",
            getattr(exc_type, "__name__", str(exc_type)),
            value,
        )
        self.set_loading(False)

    def _on_load_complete(self, result: tuple) -> None:
        data, device_path = result
        if device_path != DeviceManager.get_instance().device_path:
            self.set_loading(False)
            return
        if data:
            self.set_data(data, device_path)
        else:
            self.set_loading(False)


def build_album_list(cache: LibraryCacheLike) -> list:
    """Transform cached data into album list for grid display."""

    albums = cache.get_albums()
    album_index = cache.get_album_index()
    album_only_index = cache.get_album_only_index()
    all_tracks = cache.get_tracks()

    items = []
    for album_entry in albums:
        artist = album_entry.get("Artist (Used by Album Item)") or ""
        album = album_entry.get("Album (Used by Album Item)") or ""
        album_id = album_entry.get("album_id")
        if album_id is None:
            album_id = album_entry.get("Album ID")

        matching_tracks = []
        if album_id is not None:
            matching_tracks = [
                track
                for track in all_tracks
                if track.get("album_id") == album_id and _is_music_browser_track(track)
            ]
        elif artist:
            matching_tracks = album_index.get((album, artist), [])

        if not matching_tracks:
            matching_tracks = album_only_index.get(album, [])
            if matching_tracks and not artist:
                artist = (
                    matching_tracks[0].get("Album Artist")
                    or matching_tracks[0].get("Artist")
                    or ""
                )

        artwork_id_ref = None
        track_count = len(matching_tracks)
        year = None
        total_length_ms = 0

        if track_count > 0:
            artwork_id_ref = matching_tracks[0].get("artwork_id_ref")
            year = next(
                (
                    track.get("year")
                    for track in matching_tracks
                    if track.get("year")
                ),
                None,
            )
            total_length_ms = sum(track.get("length", 0) for track in matching_tracks)

        subtitle_parts = [artist] if artist else []
        if year and year > 0:
            subtitle_parts.append(str(year))
        subtitle_parts.append(f"{track_count} tracks")

        if track_count == 0:
            continue

        filter_key = "album_id" if album_id is not None else "Album"
        filter_value = album_id if album_id is not None else album

        items.append(
            {
                "title": album,
                "subtitle": " · ".join(subtitle_parts),
                "album": album,
                "artist": artist,
                "year": year,
                "artwork_id_ref": artwork_id_ref,
                "category": "Albums",
                "filter_key": filter_key,
                "filter_value": filter_value,
                "track_count": track_count,
                "total_length_ms": total_length_ms,
            }
        )

    return sorted(items, key=lambda item: item["title"].lower())


def build_artist_list(cache: LibraryCacheLike) -> list:
    """Transform cached data into artist list for grid display."""

    artist_index = cache.get_artist_index()

    items = []
    for artist, tracks in artist_index.items():
        track_count = len(tracks)
        artwork_id_ref = next(
            (
                track.get("artwork_id_ref")
                for track in tracks
                if track.get("artwork_id_ref")
            ),
            None,
        )
        album_count = len(set(track.get("Album", "") for track in tracks))
        total_plays = sum(track.get("play_count_1", 0) for track in tracks)

        subtitle_parts = []
        if album_count > 1:
            subtitle_parts.append(f"{album_count} albums")
        subtitle_parts.append(f"{track_count} tracks")
        if total_plays > 0:
            subtitle_parts.append(f"{total_plays} plays")

        items.append(
            {
                "title": artist,
                "subtitle": " · ".join(subtitle_parts),
                "artwork_id_ref": artwork_id_ref,
                "category": "Artists",
                "filter_key": "Artist",
                "filter_value": artist,
                "track_count": track_count,
                "album_count": album_count,
                "total_plays": total_plays,
            }
        )

    return sorted(items, key=lambda item: item["title"].lower())


def build_genre_list(cache: LibraryCacheLike) -> list:
    """Transform cached data into genre list for grid display."""

    genre_index = cache.get_genre_index()

    items = []
    for genre, tracks in genre_index.items():
        track_count = len(tracks)
        artwork_id_ref = next(
            (
                track.get("artwork_id_ref")
                for track in tracks
                if track.get("artwork_id_ref")
            ),
            None,
        )
        artist_count = len(set(track.get("Artist", "") for track in tracks))
        total_length_ms = sum(track.get("length", 0) for track in tracks)
        total_hours = total_length_ms / (1000 * 60 * 60)

        subtitle_parts = []
        if artist_count > 1:
            subtitle_parts.append(f"{artist_count} artists")
        subtitle_parts.append(f"{track_count} tracks")
        if total_hours >= 1:
            subtitle_parts.append(f"{total_hours:.1f} hours")

        items.append(
            {
                "title": genre,
                "subtitle": " · ".join(subtitle_parts),
                "artwork_id_ref": artwork_id_ref,
                "category": "Genres",
                "filter_key": "Genre",
                "filter_value": genre,
                "track_count": track_count,
                "artist_count": artist_count,
                "total_length_ms": total_length_ms,
            }
        )

    return sorted(items, key=lambda item: item["title"].lower())
