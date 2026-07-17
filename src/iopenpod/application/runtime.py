"""Runtime state owners and background helpers extracted from the GUI shell."""

from __future__ import annotations

import copy
import logging
import os
import sys
import threading
import traceback
from collections import Counter
from pathlib import Path
from typing import TypeAlias

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, pyqtSignal, pyqtSlot

from iopenpod.device.write_guard import (
    DatabaseGeneration,
    ExternalDatabaseChangeError,
    capture_database_generation,
)
from iopenpod.itunesdb_shared.album_identity import album_identity_from_mapping
from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_AUDIO, MEDIA_TYPE_AUDIO_VIDEO
from iopenpod.itunesdb_shared.playlist_properties import (
    normalize_playlist_description,
)

from .services import DeviceInfoLike, LibraryCacheLike, QuickWriteSnapshot

logger = logging.getLogger(__name__)

_PlaylistBucketKey: TypeAlias = str | None
_PlaylistCandidate: TypeAlias = tuple[dict, _PlaylistBucketKey]
_PLAYLIST_BUCKET_ORIGINS: dict[str, tuple[int, str]] = {
    "mhlp": (2, "mhlp"),
    "mhlp_podcast": (3, "mhlp_podcast"),
    "mhlp_smart": (5, "mhlp_smart"),
}
_DISPLAY_MERGE_DATASETS = {2, 3}
_DISPLAY_ONLY_PLAYLIST_KEYS = {
    "_mhsd_display_origins",
    "_mhsd_display_types",
    "_mhsd_display_merged",
    "_mhsd_display_label",
}


def _is_iopenpod_temp_artwork_path(path: str) -> bool:
    return os.path.basename(path).startswith("iopenpod-artwork-")


def _cleanup_temp_artwork_paths(paths: list[str]) -> None:
    for path in set(paths):
        if not _is_iopenpod_temp_artwork_path(path):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _is_music_browser_track(track: dict) -> bool:
    """Return whether a track belongs in the music browser indexes."""

    try:
        media_type = int(track.get("media_type", MEDIA_TYPE_AUDIO) or 0)
    except (TypeError, ValueError):
        media_type = MEDIA_TYPE_AUDIO
    return media_type == MEDIA_TYPE_AUDIO_VIDEO or bool(media_type & MEDIA_TYPE_AUDIO)


def _mhsd5_type_value(playlist: dict) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _smart_bucket_source(playlist: dict) -> str:
    return "category" if _mhsd5_type_value(playlist) else "smart"


def _is_ipod_category_playlist(playlist: dict) -> bool:
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type:
        return dataset_type == 5
    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _playlist_dataset_type(playlist: dict) -> int:
    try:
        return int(playlist.get("_mhsd_dataset_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _playlist_source_for_dataset(playlist: dict, dataset_type: int) -> str:
    if dataset_type == 5:
        return _smart_bucket_source(playlist)
    return "regular"


def _playlist_row_for_dataset(playlist: dict, dataset_type: int) -> dict:
    row = dict(playlist)
    row["_mhsd_dataset_type"] = dataset_type
    row["_mhsd_result_key"] = _result_key_for_dataset(dataset_type)
    row.setdefault("_source", _playlist_source_for_dataset(row, dataset_type))
    return _playlist_with_description(row)


def _data_uses_dataset3_playlists(data: dict | None) -> bool:
    if data is None:
        return False
    rows = data.get("mhlp_podcast")
    return isinstance(rows, list) and bool(rows)


def _is_regular_playlist_mirror_candidate(playlist: dict) -> bool:
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type not in (0, 2):
        return False
    if _is_ipod_category_playlist(playlist):
        return False
    if playlist.get("podcast_flag", 0) == 1 or playlist.get("_source") == "podcast":
        return False
    return True


def _playlist_origin_summary(playlist: dict) -> dict[str, object]:
    try:
        podcast_flag = int(playlist.get("podcast_flag", 0) or 0)
    except (TypeError, ValueError):
        podcast_flag = 0
    try:
        child_count = int(playlist.get("mhip_child_count", 0) or 0)
    except (TypeError, ValueError):
        child_count = 0
    return {
        "dataset_type": _playlist_dataset_type(playlist),
        "result_key": str(playlist.get("_mhsd_result_key") or ""),
        "source": str(playlist.get("_source") or ""),
        "title": str(playlist.get("Title") or ""),
        "podcast_flag": podcast_flag,
        "mhip_child_count": child_count,
    }


def _has_podcast_group_headers(playlist: dict) -> bool:
    items = playlist.get("items", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("podcast_group_flag", 0) or 0) == 256:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _real_playlist_item_count(playlist: dict) -> int:
    items = playlist.get("items", [])
    if not isinstance(items, list):
        try:
            return int(playlist.get("mhip_child_count", 0) or 0)
        except (TypeError, ValueError):
            return 0
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            track_id = int(item.get("track_id", 0) or 0)
        except (TypeError, ValueError):
            track_id = 0
        if track_id > 0:
            count += 1
    return count


def _display_playlist_rank(playlist: dict) -> tuple[int, int, int]:
    dataset_type = _playlist_dataset_type(playlist)
    return (
        1 if dataset_type == 3 and _has_podcast_group_headers(playlist) else 0,
        _real_playlist_item_count(playlist),
        1 if dataset_type == 2 else 0,
    )


def _origin_dataset_type(origin: dict[str, object]) -> int:
    value = origin.get("dataset_type", 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return 0
    if isinstance(value, bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _result_key_for_dataset(dataset_type: int) -> str:
    return {2: "mhlp", 3: "mhlp_podcast", 5: "mhlp_smart"}.get(
        dataset_type,
        "mhlp",
    )


def _origin_result_key(origin: dict[str, object], dataset_type: int) -> str:
    result_key = origin.get("result_key")
    if isinstance(result_key, str) and result_key:
        return result_key
    return _result_key_for_dataset(dataset_type)


def _without_display_playlist_keys(playlist: dict) -> dict:
    return {
        key: value
        for key, value in playlist.items()
        if key not in _DISPLAY_ONLY_PLAYLIST_KEYS
    }


def _find_live_playlist_for_origin(
    data: dict | None,
    playlist_id: object,
    dataset_type: int,
    result_key: str,
) -> dict | None:
    if data is None or not playlist_id:
        return None
    bucket = data.get(result_key, [])
    if not isinstance(bucket, list):
        return None
    for playlist in bucket:
        if not isinstance(playlist, dict):
            continue
        if playlist.get("playlist_id") != playlist_id:
            continue
        row_dataset = _playlist_dataset_type(playlist) or dataset_type
        if row_dataset == dataset_type:
            return playlist
    return None


def _display_origin_save_targets(playlist: dict, data: dict | None) -> list[dict]:
    origins = playlist.get("_mhsd_display_origins")
    if not isinstance(origins, list) or len(origins) <= 1:
        return []

    playlist_id = playlist.get("playlist_id", 0)
    edited_fields = _without_display_playlist_keys(playlist)
    rows: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for origin in origins:
        if not isinstance(origin, dict):
            continue
        dataset_type = _origin_dataset_type(origin)
        if dataset_type not in (2, 3, 5):
            continue
        result_key = _origin_result_key(origin, dataset_type)
        origin_key = (dataset_type, result_key)
        if origin_key in seen:
            continue
        seen.add(origin_key)
        live_row = _find_live_playlist_for_origin(
            data,
            playlist_id,
            dataset_type,
            result_key,
        )
        row = dict(live_row or {})
        row.update(edited_fields)
        row["playlist_id"] = playlist_id
        row["_mhsd_dataset_type"] = dataset_type
        row["_mhsd_result_key"] = result_key
        row["_source"] = _playlist_source_for_dataset(row, dataset_type)
        rows.append(_playlist_with_description(row))
    return rows


def _playlist_with_display_origins(playlist: dict, origins: list[dict[str, object]]) -> dict:
    row = dict(playlist)
    sorted_origins = sorted(
        origins,
        key=_origin_dataset_type,
    )
    represented_types = [
        dataset_type
        for origin in sorted_origins
        if (dataset_type := _origin_dataset_type(origin))
    ]
    row["_mhsd_display_origins"] = sorted_origins
    row["_mhsd_display_types"] = represented_types
    row["_mhsd_display_merged"] = len(set(represented_types)) > 1
    row["_mhsd_display_label"] = (
        " + ".join(f"MHSD type {dataset_type}" for dataset_type in represented_types)
        if represented_types
        else "MHSD type unknown"
    )
    if row.get("_mhsd_display_merged"):
        row["mhip_child_count"] = _real_playlist_item_count(row)
    return row


def display_playlists_from_rows(playlists: list[dict]) -> list[dict]:
    """Return a UI projection that merges duplicate MHSD type 2/3 rows.

    The raw cache intentionally preserves every parsed row for writes. This
    helper is the final display projection: same-ID type 2/type 3 twins become
    one visible playlist, while the returned row carries explicit origin
    metadata so the UI can say which MHSD types it represents.
    """

    groups: dict[int, list[dict]] = {}
    passthrough: list[dict] = []
    for playlist in playlists:
        dataset_type = _playlist_dataset_type(playlist)
        try:
            playlist_id = int(playlist.get("playlist_id", 0) or 0)
        except (TypeError, ValueError):
            playlist_id = 0
        if playlist_id and dataset_type in _DISPLAY_MERGE_DATASETS:
            groups.setdefault(playlist_id, []).append(playlist)
        else:
            passthrough.append(
                _playlist_with_display_origins(
                    playlist,
                    [_playlist_origin_summary(playlist)],
                )
            )

    result = list(passthrough)
    for grouped in groups.values():
        dataset_types = {_playlist_dataset_type(playlist) for playlist in grouped}
        origins = [_playlist_origin_summary(playlist) for playlist in grouped]
        if dataset_types == _DISPLAY_MERGE_DATASETS and len(grouped) > 1:
            representative = max(grouped, key=_display_playlist_rank)
            result.append(_playlist_with_display_origins(representative, origins))
        else:
            result.extend(
                _playlist_with_display_origins(
                    playlist,
                    [_playlist_origin_summary(playlist)],
                )
                for playlist in grouped
            )

    return result


def _playlist_with_description(playlist: dict) -> dict:
    return normalize_playlist_description(playlist)


def _playlist_with_origin(playlist: dict, dataset_type: int, result_key: str) -> dict:
    row = {
        **playlist,
        "_mhsd_dataset_type": dataset_type,
        "_mhsd_result_key": result_key,
    }
    row["_source"] = _playlist_source_for_dataset(row, dataset_type)
    return _playlist_with_description(row)


def _playlist_live_origins(
    data: dict | None,
    playlist_id: object,
) -> list[tuple[int, str]]:
    """Return the live MHSD origins currently using ``playlist_id``.

    Dataset 2 and 3 rows commonly duplicate playlist IDs on classic iPods. That
    duplication is meaningful, so callers must not collapse matches by ID alone.
    """

    if data is None or not playlist_id:
        return []

    matches: list[tuple[int, str]] = []
    for bucket_key, (dataset_type, result_key) in _PLAYLIST_BUCKET_ORIGINS.items():
        bucket = data.get(bucket_key, [])
        if not isinstance(bucket, list):
            continue
        for playlist in bucket:
            if not isinstance(playlist, dict):
                continue
            if playlist.get("playlist_id") == playlist_id:
                matches.append((
                    _playlist_dataset_type(playlist) or dataset_type,
                    str(playlist.get("_mhsd_result_key") or result_key),
                ))
    return matches


def _playlist_with_known_edit_origin(
    playlist: dict,
    data: dict | None,
) -> dict | None:
    """Keep existing playlist edits tied to their original MHSD location.

    New playlists may be routed by their requested kind. Existing edits are
    different: if the UI lost the parsed origin, choosing a bucket by flags would
    manufacture a move the iPod database never asked for.
    """

    if _playlist_dataset_type(playlist):
        return playlist
    if playlist.get("_isNew") is not False:
        return playlist

    playlist_id = playlist.get("playlist_id")
    matches = _playlist_live_origins(data, playlist_id)
    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        dataset_type, result_key = unique_matches[0]
        playlist["_mhsd_dataset_type"] = dataset_type
        playlist["_mhsd_result_key"] = result_key
        playlist.setdefault(
            "_source",
            _playlist_source_for_dataset(playlist, dataset_type),
        )
        logger.warning(
            "Restored missing MHSD origin for playlist edit '%s' "
            "(id=0x%016X, mhsd=%s, key=%s).",
            playlist.get("Title", "?"),
            int(playlist_id or 0),
            dataset_type,
            result_key,
        )
        return playlist

    if unique_matches:
        locations = ", ".join(
            f"mhsd {dataset_type}/{result_key}"
            for dataset_type, result_key in unique_matches
        )
        logger.error(
            "Refusing playlist edit without MHSD origin: '%s' "
            "(id=0x%016X) appears in %s.",
            playlist.get("Title", "?"),
            int(playlist_id or 0),
            locations,
        )
    else:
        logger.error(
            "Refusing playlist edit without MHSD origin: '%s' "
            "(id=0x%016X) has no matching live row.",
            playlist.get("Title", "?"),
            int(playlist_id or 0),
        )
    return None


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

        identity = album_identity_from_mapping(track)
        album = identity.album or "Unknown Album"
        artist = identity.artist or "Unknown Artist"
        album_artist = identity.album_artist or artist
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
            from iopenpod.infrastructure.settings_runtime import get_default_runtime

            settings_runtime = get_default_runtime()
            state = settings_runtime.load_device_settings(
                self._ipod_root,
                self._device_key,
                settings_runtime.get_global_settings(),
            )
            if state.load_error:
                from iopenpod.device.write_guard import DeviceWriteSafetyError

                raise DeviceWriteSafetyError(state.load_error)
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
        if ipod is not None:
            from iopenpod.device import require_exact_model_number

            require_exact_model_number(ipod)
        self._sync_device_info(ipod)
        self._discovered_ipod = ipod

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
            from iopenpod.infrastructure.settings_runtime import get_default_runtime

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
        if path:
            from iopenpod.device import (
                DeviceInfo,
                ensure_device_itunes_database,
                require_exact_model_number,
            )

            require_exact_model_number(self._discovered_ipod)
            if isinstance(self._discovered_ipod, DeviceInfo):
                try:
                    ensure_device_itunes_database(path, self._discovered_ipod)
                except Exception as exc:
                    logger.error(
                        "iPod selection stopped before activation: path=%s error=%s",
                        path,
                        exc,
                    )
                    raise
        self.device_changing.emit()
        self.cancel_all_operations()
        iTunesDBCache.get_instance().clear()
        self._cancel_device_settings_loads()
        self._device_path = path
        if path is None:
            self._discovered_ipod = None
            from iopenpod.device import clear_current_device

            clear_current_device()
        try:
            from iopenpod.infrastructure.settings_runtime import (
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
        from iopenpod.device import resolve_itdb_path

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
            from iopenpod.device import has_virtual_ipod_info

            if has_virtual_ipod_info(path):
                return True
        except Exception:
            pass
        ipod_control = os.path.join(path, "iPod_Control")
        return os.path.isdir(ipod_control)

    @staticmethod
    def _sync_device_info(ipod) -> None:
        from iopenpod.device import clear_current_device, set_current_device

        if ipod is None:
            clear_current_device()
            return
        set_current_device(ipod)


class iTunesDBCache(QObject):
    """Cache for parsed iTunesDB data. Loads once when device selected."""

    data_ready = pyqtSignal()
    load_failed = pyqtSignal(str)
    _instance: iTunesDBCache | None = None

    playlists_changed = pyqtSignal()
    playlist_quick_sync = pyqtSignal()
    tracks_changed = pyqtSignal()
    track_fields_changed = pyqtSignal(object)
    photos_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._data: dict | None = None
        self._device_path: str | None = None
        self._is_loading: bool = False
        self._lock = threading.RLock()
        self._album_index: dict | None = None
        self._album_only_index: dict | None = None
        self._artist_index: dict | None = None
        self._genre_index: dict | None = None
        self._track_id_index: dict | None = None
        self._photo_db = None
        self._user_playlists: list[dict] = []
        self._track_edits: dict[int, dict[str, tuple]] = {}
        self._track_artwork_edits: dict[int, str] = {}
        self._quick_write_revision = 0
        self._database_generation: DatabaseGeneration | None = None
        from iopenpod.sync.photos import PhotoEditState

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
            _cleanup_temp_artwork_paths(list(self._track_artwork_edits.values()))
            self._track_edits.clear()
            self._track_artwork_edits.clear()
            self._quick_write_revision += 1
            self._database_generation = None
            from iopenpod.sync.photos import PhotoEditState

            self._photo_edits = PhotoEditState()

    def invalidate(self) -> None:
        with self._lock:
            self._data = None
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None
            self._database_generation = None

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

        result: list[dict] = []

        for playlist in data.get("mhlp", []):
            result.append(_playlist_with_origin(playlist, 2, "mhlp"))

        for playlist in data.get("mhlp_podcast", []):
            result.append(_playlist_with_origin(playlist, 3, "mhlp_podcast"))

        for playlist in data.get("mhlp_smart", []):
            result.append(_playlist_with_origin(playlist, 5, "mhlp_smart"))

        with self._lock:
            for user_playlist in self._user_playlists:
                playlist_id = user_playlist.get("playlist_id", 0)
                dataset_type = _playlist_dataset_type(user_playlist)
                replaced = False
                if playlist_id and dataset_type:
                    for index, row in enumerate(result):
                        if (
                            row.get("playlist_id") == playlist_id
                            and _playlist_dataset_type(row) == dataset_type
                        ):
                            result[index] = user_playlist
                            replaced = True
                            break
                if not replaced:
                    result.append(user_playlist)

        return result

    def get_display_playlists(self) -> list:
        return display_playlists_from_rows(self.get_playlists())

    def save_user_playlist(self, playlist: dict) -> None:
        import random

        with self._lock:
            playlist = _playlist_with_description(playlist)
            playlist_id = playlist.get("playlist_id", 0)
            if not playlist_id:
                playlist_id = random.getrandbits(64)
                playlist["playlist_id"] = playlist_id

            target_playlists = _display_origin_save_targets(playlist, self._data)
            if not target_playlists:
                resolved_playlist = _playlist_with_known_edit_origin(playlist, self._data)
                if resolved_playlist is None:
                    return
                if (
                    playlist.get("_isNew") is not False
                    and _data_uses_dataset3_playlists(self._data)
                    and _is_regular_playlist_mirror_candidate(resolved_playlist)
                ):
                    target_playlists = [
                        _playlist_row_for_dataset(resolved_playlist, 2),
                        _playlist_row_for_dataset(resolved_playlist, 3),
                    ]
                else:
                    target_playlists = [resolved_playlist]

            replaced_count = 0
            for target_playlist in target_playlists:
                items = target_playlist.get("items")
                if isinstance(items, list):
                    target_playlist["mhip_child_count"] = len(items)

                replaced = False
                target_dataset = _playlist_dataset_type(target_playlist)
                for index, user_playlist in enumerate(self._user_playlists):
                    same_origin = _playlist_dataset_type(user_playlist) == target_dataset
                    if (
                        user_playlist.get("playlist_id") == playlist_id
                        and same_origin
                    ):
                        self._user_playlists[index] = target_playlist
                        replaced = True
                        replaced_count += 1
                        break
                if not replaced:
                    self._user_playlists.append(target_playlist)
            self._quick_write_revision += 1

        logger.info(
            "User playlist saved: '%s' (id=0x%016X, row_count=%d, new=%s)",
            playlist.get("Title", "?"),
            playlist_id,
            len(target_playlists),
            replaced_count < len(target_playlists),
        )
        self.playlists_changed.emit()

    def remove_user_playlist(
        self, playlist_id: int, dataset_type: int | None = None
    ) -> bool:
        """Remove one playlist without collapsing same IDs across MHSD buckets."""
        target_dataset = int(dataset_type or 0)

        def row_dataset(playlist: dict, bucket_key: str | None = None) -> int:
            dataset = _playlist_dataset_type(playlist)
            if dataset:
                return dataset
            return {"mhlp": 2, "mhlp_podcast": 3, "mhlp_smart": 5}.get(
                bucket_key or "", 0
            )

        def matches(playlist: dict, bucket_key: str | None = None) -> bool:
            if playlist.get("playlist_id") != playlist_id:
                return False
            if not target_dataset:
                return True
            return row_dataset(playlist, bucket_key) == target_dataset

        with self._lock:
            data = self._data
            candidates: list[_PlaylistCandidate] = [
                (playlist, None) for playlist in self._user_playlists
            ]
            if data is not None:
                for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
                    bucket = data.get(key, [])
                    if not isinstance(bucket, list):
                        continue
                    candidates.extend(
                        (playlist, key)
                        for playlist in bucket
                        if isinstance(playlist, dict)
                    )
            for playlist, key in candidates:
                if matches(playlist, key) and playlist.get("master_flag"):
                    return False

            before = len(self._user_playlists)
            self._user_playlists = [
                playlist
                for playlist in self._user_playlists
                if not matches(playlist)
            ]
            removed = len(self._user_playlists) < before
            if data is not None:
                for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
                    bucket = data.get(key, [])
                    kept = [
                        playlist
                        for playlist in bucket
                        if not matches(playlist, key)
                    ]
                    if len(kept) != len(bucket):
                        data[key] = kept
                        removed = True
            if removed:
                self._quick_write_revision += 1
        if removed:
            self.playlists_changed.emit()
        return removed

    def rename_master_playlist(self, new_name: str) -> bool:
        with self._lock:
            data = self._data
            if data is None:
                return False
            renamed = False
            for key in ("mhlp", "mhlp_podcast"):
                for playlist in data.get(key, []):
                    if playlist.get("master_flag"):
                        playlist["Title"] = new_name
                        renamed = True
            if renamed:
                self._quick_write_revision += 1
        if renamed:
            self.playlists_changed.emit()
        return renamed

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

                row = _playlist_with_description(dict(pending))
                row = _playlist_with_known_edit_origin(row, data)
                if row is None:
                    continue
                items = row.get("items")
                if isinstance(items, list):
                    row["mhip_child_count"] = len(items)

                dataset_type = _playlist_dataset_type(row)
                if dataset_type == 3:
                    target = podcast
                    row.setdefault("_mhsd_dataset_type", 3)
                    row.setdefault("_mhsd_result_key", "mhlp_podcast")
                elif dataset_type == 5 or _is_ipod_category_playlist(row):
                    target = smart
                    row.setdefault("_mhsd_dataset_type", 5)
                    row.setdefault("_mhsd_result_key", "mhlp_smart")
                elif row.get("podcast_flag", 0) == 1 or row.get("_source") == "podcast":
                    target = podcast
                    row.setdefault("_mhsd_dataset_type", 3)
                    row.setdefault("_mhsd_result_key", "mhlp_podcast")
                else:
                    target = regular
                    row.setdefault("_mhsd_dataset_type", 2)
                    row.setdefault("_mhsd_result_key", "mhlp")

                dataset_type = _playlist_dataset_type(row)

                found_in_target = False
                for bucket in buckets:
                    for index, existing in enumerate(bucket):
                        if (
                            existing.get("playlist_id") == playlist_id
                            and _playlist_dataset_type(existing) in (0, dataset_type)
                        ):
                            if bucket is target:
                                bucket[index] = row
                                found_in_target = True
                            else:
                                del bucket[index]
                            break
                    else:
                        continue

                if not found_in_target:
                    target.append(row)

            self._user_playlists.clear()

        self.playlists_changed.emit()

    def update_track_flags(self, tracks: list[dict], changes: dict) -> None:
        with self._lock:
            edited = False
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
                    edited = True

            if edited:
                self._quick_write_revision += 1

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
        self.track_fields_changed.emit(frozenset(changes))
        self.tracks_changed.emit()

    def update_track_flags_by_track(self, tracks: list[dict], changes_by_track: dict[int, dict]) -> None:
        with self._lock:
            edited = 0
            field_counts: Counter[str] = Counter()
            for track in tracks:
                db_track_id = track.get("db_track_id", track.get("db_id", 0))
                if not db_track_id:
                    continue
                changes = changes_by_track.get(id(track), {})
                if not changes:
                    continue
                edits = self._track_edits.setdefault(db_track_id, {})
                for key, value in changes.items():
                    if key in edits:
                        original, _ = edits[key]
                        edits[key] = (original, value)
                    else:
                        edits[key] = (track.get(key), value)
                    track[key] = value
                    field_counts[key] += 1
                edited += 1

            if edited:
                self._quick_write_revision += 1

            if self._data is not None:
                (
                    self._album_index,
                    self._album_only_index,
                    self._artist_index,
                    self._genre_index,
                    self._track_id_index,
                ) = _build_track_indexes(list(self._data.get("mhlt", [])))

        logger.info(
            "Track metadata updated on %d track(s) with library tag fixes: %s",
            edited,
            ", ".join(f"{key}={count}" for key, count in sorted(field_counts.items())),
        )
        if edited:
            self.track_fields_changed.emit(frozenset(field_counts))
            self.tracks_changed.emit()

    def update_track_artwork(self, tracks: list[dict], image_path: str) -> None:
        with self._lock:
            edited = 0
            for track in tracks:
                db_track_id = track.get("db_track_id", track.get("db_id", 0))
                if not db_track_id:
                    continue
                db_track_id = int(db_track_id)
                previous = self._track_artwork_edits.get(db_track_id)
                if previous and previous != image_path:
                    still_used = any(
                        path == previous
                        for other_id, path in self._track_artwork_edits.items()
                        if other_id != db_track_id
                    )
                    if not still_used:
                        _cleanup_temp_artwork_paths([previous])
                self._track_artwork_edits[db_track_id] = image_path
                track["_iop_pending_artwork_path"] = image_path
                edited += 1

            if edited:
                self._quick_write_revision += 1

        logger.info("Track artwork updated on %d track(s): %s", edited, image_path)
        self.track_fields_changed.emit(frozenset({"artwork"}))
        self.tracks_changed.emit()

    def get_track_edits(self) -> dict[int, dict[str, tuple]]:
        with self._lock:
            return dict(self._track_edits)

    def get_track_artwork_edits(self) -> dict[int, str]:
        with self._lock:
            return dict(self._track_artwork_edits)

    def has_pending_track_edits(self) -> bool:
        with self._lock:
            return bool(self._track_edits) or bool(self._track_artwork_edits)

    def clear_track_edits(self) -> None:
        with self._lock:
            _cleanup_temp_artwork_paths(list(self._track_artwork_edits.values()))
            self._track_edits.clear()
            self._track_artwork_edits.clear()

    def get_photo_edits(self):
        with self._lock:
            return self._photo_edits

    def clear_photo_edits(self) -> None:
        from iopenpod.sync.photos import PhotoEditState

        with self._lock:
            self._photo_edits = PhotoEditState()
        self.photos_changed.emit()

    def clear_pending_sync_state(self) -> None:
        self.clear_pending_playlists()
        self.clear_track_edits()
        self.clear_photo_edits()

    def discard_quick_write_state(self) -> None:
        """Discard iTunesDB quick-write edits while keeping other staging."""
        with self._lock:
            _cleanup_temp_artwork_paths(list(self._track_artwork_edits.values()))
            self._user_playlists.clear()
            self._track_edits.clear()
            self._track_artwork_edits.clear()
            self._quick_write_revision += 1

    def get_quick_write_revision(self) -> int:
        with self._lock:
            return self._quick_write_revision

    def capture_quick_write_state(self) -> QuickWriteSnapshot:
        """Atomically copy staged iTunesDB inputs and their cache revision."""
        with self._lock:
            return QuickWriteSnapshot(
                tracks=copy.deepcopy(self.get_tracks()),
                playlists=copy.deepcopy(self.get_playlists()),
                track_edits=copy.deepcopy(self._track_edits),
                artwork_sources=copy.deepcopy(self._track_artwork_edits),
                revision=self._quick_write_revision,
                database_generation=self._database_generation,
            )

    def commit_quick_write_state(self, expected_revision: int) -> bool:
        """Finalize a legacy quick-write result without a generation update."""
        return self.commit_quick_write_state_with_generation(expected_revision, None)

    def commit_quick_write_state_with_generation(
        self,
        expected_revision: int,
        database_generation: DatabaseGeneration | None,
    ) -> bool:
        """Finalize an unchanged quick-write snapshot without reparsing."""
        with self._lock:
            if expected_revision != self._quick_write_revision:
                return False
            self.commit_user_playlists()
            _cleanup_temp_artwork_paths(list(self._track_artwork_edits.values()))
            self._track_edits.clear()
            self._track_artwork_edits.clear()
            if database_generation is not None:
                self._database_generation = database_generation
            self._quick_write_revision += 1

        return True

    def get_database_generation(self) -> DatabaseGeneration | None:
        """Return the on-device generation backing the live parsed cache."""
        with self._lock:
            return self._database_generation

    def reload_after_itunesdb_write(self) -> None:
        """Clear committed iTunesDB staging and reload the device database."""
        self.discard_quick_write_state()
        with self._lock:
            self._data = None
            self._is_loading = False
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None
            self._photo_db = None
            self._database_generation = None
        self.start_loading()

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

    def pop_track_artwork_edits(self) -> dict[int, str]:
        with self._lock:
            edits = dict(self._track_artwork_edits)
            self._track_artwork_edits.clear()
            return edits

    def set_data(
        self,
        data: dict,
        device_path: str,
        database_generation: DatabaseGeneration | None = None,
    ) -> None:
        for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
            bucket = data.get(key, [])
            if isinstance(bucket, list):
                for playlist in bucket:
                    if isinstance(playlist, dict):
                        _playlist_with_description(playlist)

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
            self._database_generation = database_generation
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

    def _load_data(
        self,
        device_path: str,
        itunesdb_path: str | None,
    ) -> tuple[dict, str, list[str], DatabaseGeneration | None]:
        data: dict = {}
        load_errors: list[str] = []
        database_generation: DatabaseGeneration | None = None
        if not itunesdb_path:
            message = f"No iTunesDB path available for device: {device_path}"
            logger.warning(message)
            return data, device_path, [message], None

        try:
            from iopenpod.itunesdb_parser.ipod_library import load_ipod_library

            committed_playcounts = False
            try:
                from iopenpod.sync._db_io import commit_playcounts_if_needed

                committed_playcounts = commit_playcounts_if_needed(
                    Path(device_path),
                )
            except Exception as exc:
                logger.warning("Play Counts auto-commit failed", exc_info=True)
                from iopenpod.device.write_guard import DeviceWriteSafetyError

                if isinstance(exc, DeviceWriteSafetyError):
                    load_errors.append(
                        "Play Counts were not committed because the iPod is not "
                        f"safe to write: {exc}"
                    )

            generation_before_parse = capture_database_generation(device_path)
            parsed = load_ipod_library(
                itunesdb_path,
                merge_playcounts=not committed_playcounts,
            ) or {}
            generation_after_parse = capture_database_generation(device_path)
            if generation_before_parse != generation_after_parse:
                raise ExternalDatabaseChangeError(
                    "The iPod database changed while iOpenPod was loading it. "
                    "Close other device-management apps and reload the iPod."
                )
            database_generation = generation_after_parse
            if isinstance(parsed, dict):
                data = parsed
            else:
                logger.warning(
                    "iTunesDB parser returned unexpected type: %s",
                    type(parsed).__name__,
                )
        except Exception as exc:
            logger.exception("Failed to load iTunesDB for device: %s", device_path)
            load_errors.append(f"Could not load iTunesDB: {exc}")

        try:
            from iopenpod.sync.photos import PhotoDB, read_photo_db

            data["photodb"] = read_photo_db(device_path)
        except Exception as exc:
            logger.exception(
                "Failed to load photo database for device: %s",
                device_path,
            )
            from iopenpod.sync.photos import PhotoDB

            data["photodb"] = PhotoDB()
            load_errors.append(f"Could not load photo database: {exc}")

        return (data, device_path, load_errors, database_generation)

    def _on_load_error(self, error: tuple) -> None:
        exc_type, value, _traceback = error
        logger.error(
            "Device load worker failed: %s: %s",
            getattr(exc_type, "__name__", str(exc_type)),
            value,
        )
        self.set_loading(False)
        self.load_failed.emit(str(value))

    def _on_load_complete(
        self,
        result: (
            tuple[dict, str]
            | tuple[dict, str, list[str]]
            | tuple[dict, str, list[str], DatabaseGeneration | None]
        ),
    ) -> None:
        data = result[0]
        device_path = result[1]
        load_errors = result[2] if len(result) >= 3 else []
        database_generation = result[3] if len(result) >= 4 else None
        if device_path != DeviceManager.get_instance().device_path:
            self.set_loading(False)
            return
        if data and (len(result) < 4 or database_generation is not None):
            self.set_data(data, device_path, database_generation)
        else:
            self.set_loading(False)
        if load_errors:
            self.load_failed.emit("\n".join(str(error) for error in load_errors))


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
        filter_album_id = None
        if album_id is not None:
            album_id_tracks = [
                track
                for track in all_tracks
                if track.get("album_id") == album_id
            ]
            matching_tracks = [
                track
                for track in album_id_tracks
                if _is_music_browser_track(track)
            ]
            if matching_tracks:
                filter_album_id = album_id
            elif album_id_tracks:
                continue
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

        filter_key = "album_id" if filter_album_id is not None else None
        filter_value = filter_album_id

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
