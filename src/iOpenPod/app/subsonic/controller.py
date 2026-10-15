"""Qt controller coordinating Subsonic server network tasks in background threads."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iPodDB.library import PlaylistKind

from .client import SubsonicClient, SubsonicConnectionError
from .credentials import SubsonicCredentialStore, SystemSubsonicCredentialStore
from .models import (
    SubsonicPlaylistMapping,
    SubsonicSyncMode,
    SubsonicSyncResult,
)
from .sync import index_library_tracks, match_subsonic_entries

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.library_workspace import LibraryWorkspace

    from .models import SubsonicPlaylist

logger = logging.getLogger(__name__)


class _ConnectionSignals(QObject):
    result = Signal(bool, str)


class _TestConnectionWork(QRunnable):
    def __init__(self, url: str, username: str, password: str) -> None:
        super().__init__()
        self.url = url
        self.username = username
        self.password = password
        self.signals = _ConnectionSignals()

    def run(self) -> None:
        try:
            client = SubsonicClient(self.url, self.username, self.password)
            client.ping()
            self.signals.result.emit(True, "")
        except SubsonicConnectionError as exc:
            self.signals.result.emit(False, str(exc))
        except Exception as exc:
            self.signals.result.emit(False, f"Connection failed: {exc}")


class _PlaylistSignals(QObject):
    loaded = Signal(object)
    error = Signal(str)


class _LoadPlaylistsWork(QRunnable):
    def __init__(self, url: str, username: str, password: str) -> None:
        super().__init__()
        self.url = url
        self.username = username
        self.password = password
        self.signals = _PlaylistSignals()

    def run(self) -> None:
        try:
            client = SubsonicClient(self.url, self.username, self.password)
            playlists = client.get_playlists()
            self.signals.loaded.emit(playlists)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class _SyncSignals(QObject):
    matched = Signal(object, object)
    error = Signal(str)


class _SyncPlaylistsWork(QRunnable):
    def __init__(
        self,
        client: SubsonicClient,
        mappings: tuple[SubsonicPlaylistMapping, ...],
        track_index: dict[tuple[str, str], int],
    ) -> None:
        super().__init__()
        self.client = client
        self.mappings = mappings
        self.track_index = track_index
        self.cancelled = threading.Event()
        self.signals = _SyncSignals()

    def run(self) -> None:
        try:
            matched_items: list[
                tuple[SubsonicPlaylistMapping, tuple[int, ...], int]
            ] = []
            errors: list[str] = []
            for mapping in self.mappings:
                if self.cancelled.is_set():
                    return
                try:
                    entries = self.client.get_playlist(mapping.subsonic_id)
                except Exception as exc:
                    err_msg = f"Failed to fetch Subsonic playlist '{mapping.subsonic_name}': {exc}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    continue

                if self.cancelled.is_set():
                    return

                matched_ids, unmatched = match_subsonic_entries(
                    entries, self.track_index
                )
                matched_items.append((mapping, matched_ids, unmatched))

            if self.cancelled.is_set():
                return
            self.signals.matched.emit(tuple(matched_items), tuple(errors))
        except Exception as exc:
            if not self.cancelled.is_set():
                self.signals.error.emit(f"Subsonic sync failed: {exc}")


class SubsonicController(QObject):
    """Coordinates background network requests and playlist synchronization."""

    connectionTested = Signal(bool, str)
    playlistsLoaded = Signal(object)
    syncStarted = Signal()
    syncFinished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        settings: SettingsService,
        credentials: SubsonicCredentialStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._credentials: SubsonicCredentialStore = (
            credentials if credentials is not None else SystemSubsonicCredentialStore()
        )
        self._pool = QThreadPool.globalInstance()
        self._active_workspace: LibraryWorkspace | None = None
        self._test_job: _TestConnectionWork | None = None
        self._load_job: _LoadPlaylistsWork | None = None
        self._sync_job: _SyncPlaylistsWork | None = None
        self._cached_playlists: tuple[SubsonicPlaylist, ...] = ()

    @property
    def cached_playlists(self) -> tuple[SubsonicPlaylist, ...]:
        return self._cached_playlists

    @property
    def settings(self) -> SettingsService:
        return self._settings

    @property
    def credentials(self) -> SubsonicCredentialStore:
        return self._credentials

    def test_connection(self, url: str, username: str, password: str) -> None:
        """Test server reachability and credentials in a background thread."""
        work = _TestConnectionWork(url, username, password)
        self._test_job = work
        work.signals.result.connect(
            self._handle_connection_tested, Qt.ConnectionType.QueuedConnection
        )
        self._pool.start(work)

    @Slot(bool, str)
    def _handle_connection_tested(self, success: bool, message: str) -> None:
        self._test_job = None
        self.connectionTested.emit(success, message)

    def load_playlists(self, url: str, username: str, password: str) -> None:
        """Fetch remote playlists in a background thread."""
        work = _LoadPlaylistsWork(url, username, password)
        self._load_job = work
        work.signals.loaded.connect(
            self._handle_playlists_loaded, Qt.ConnectionType.QueuedConnection
        )
        work.signals.error.connect(
            self._handle_load_error, Qt.ConnectionType.QueuedConnection
        )
        self._pool.start(work)

    @Slot(object)
    def _handle_playlists_loaded(self, playlists: object) -> None:
        self._load_job = None
        if isinstance(playlists, tuple):
            self._cached_playlists = playlists
        self.playlistsLoaded.emit(playlists)

    @Slot(str)
    def _handle_load_error(self, message: str) -> None:
        self._load_job = None
        self.error.emit(message)

    def sync_playlists(
        self,
        workspace: LibraryWorkspace,
        mappings: tuple[SubsonicPlaylistMapping, ...],
        url: str,
        username: str,
        password: str,
    ) -> None:
        """Execute playlist sync in a background thread, applying changes to workspace on main thread."""
        if not mappings:
            self.syncFinished.emit(
                SubsonicSyncResult(
                    playlists_synced=0, tracks_matched=0, tracks_unmatched=0
                )
            )
            return

        self._active_workspace = workspace
        self.syncStarted.emit()
        track_index = index_library_tracks(workspace.tracks)
        client = SubsonicClient(url, username, password)
        work = _SyncPlaylistsWork(client, mappings, track_index)
        self._sync_job = work
        work.signals.matched.connect(
            self._apply_sync_results, Qt.ConnectionType.QueuedConnection
        )
        work.signals.error.connect(
            self._handle_sync_error, Qt.ConnectionType.QueuedConnection
        )
        self._pool.start(work)

    @Slot(object, object)
    def _apply_sync_results(
        self,
        matched_items: tuple[tuple[SubsonicPlaylistMapping, tuple[int, ...], int], ...],
        errors: tuple[str, ...],
    ) -> None:
        self._sync_job = None
        workspace = self._active_workspace
        if workspace is None:
            self.error.emit("Library workspace was disconnected during sync.")
            return

        playlists_synced = 0
        total_matched = 0
        total_unmatched = 0
        all_errors = list(errors)

        for mapping, matched_ids, unmatched in matched_items:
            total_matched += len(matched_ids)
            total_unmatched += unmatched

            if not matched_ids:
                logger.info(
                    "Subsonic playlist '%s' has no matching tracks in iPod library",
                    mapping.subsonic_name,
                )
                continue

            try:
                if mapping.target_ipod_id is None:
                    workspace.create(
                        kind=PlaylistKind.PLAYLIST,
                        name=mapping.subsonic_name,
                        track_ids=matched_ids,
                    )
                    playlists_synced += 1
                else:
                    existing = workspace.playlist(mapping.target_ipod_id)
                    if existing is None:
                        workspace.create(
                            kind=PlaylistKind.PLAYLIST,
                            name=mapping.subsonic_name,
                            track_ids=matched_ids,
                        )
                        playlists_synced += 1
                    elif mapping.mode == SubsonicSyncMode.OVERWRITE:
                        workspace.set_tracks(mapping.target_ipod_id, matched_ids)
                        playlists_synced += 1
                    else:
                        existing_ids = tuple(
                            entry.track_id for entry in existing.entries
                        )
                        existing_set = set(existing_ids)
                        combined = existing_ids + tuple(
                            tid for tid in matched_ids if tid not in existing_set
                        )
                        workspace.set_tracks(mapping.target_ipod_id, combined)
                        playlists_synced += 1
            except Exception as exc:
                err_msg = f"Could not apply playlist '{mapping.subsonic_name}': {exc}"
                logger.error(err_msg, exc_info=True)
                all_errors.append(err_msg)

        result = SubsonicSyncResult(
            playlists_synced=playlists_synced,
            tracks_matched=total_matched,
            tracks_unmatched=total_unmatched,
            errors=tuple(all_errors),
        )
        self.syncFinished.emit(result)

    @Slot(str)
    def _handle_sync_error(self, message: str) -> None:
        self._sync_job = None
        self.error.emit(message)

    def cancel(self) -> None:
        """Cancel any active playlist sync work."""
        if self._sync_job is not None:
            self._sync_job.cancelled.set()
            self._sync_job = None

    def shutdown(self) -> None:
        """Cancel pending tasks and release references before exit."""
        self.cancel()
        self._test_job = None
        self._load_job = None
