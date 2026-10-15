"""Qt controller coordinating Subsonic server network tasks in background threads."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from iPodDB.library import PlaylistKind

from .client import SubsonicClient, SubsonicConnectionError
from .models import (
    SubsonicPlaylistMapping,
    SubsonicSyncMode,
    SubsonicSyncResult,
)
from .sync import index_library_tracks, match_subsonic_entries

if TYPE_CHECKING:

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.library_workspace import LibraryWorkspace

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
        self.signals = _SyncSignals()

    def run(self) -> None:
        try:
            matched_items: list[tuple[SubsonicPlaylistMapping, tuple[int, ...], int]] = []
            errors: list[str] = []
            for mapping in self.mappings:
                try:
                    entries = self.client.get_playlist(mapping.subsonic_id)
                except Exception as exc:
                    err_msg = f"Failed to fetch Subsonic playlist '{mapping.subsonic_name}': {exc}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    continue

                matched_ids, unmatched = match_subsonic_entries(
                    entries, self.track_index
                )
                matched_items.append((mapping, matched_ids, unmatched))

            self.signals.matched.emit(tuple(matched_items), tuple(errors))
        except Exception as exc:
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._pool = QThreadPool.globalInstance()
        self._active_workspace: LibraryWorkspace | None = None

    @property
    def settings(self) -> SettingsService:
        return self._settings

    def test_connection(self, url: str, username: str, password: str) -> None:
        """Test server reachability and credentials in a background thread."""
        work = _TestConnectionWork(url, username, password)
        work.signals.result.connect(self.connectionTested.emit)
        self._pool.start(work)

    def load_playlists(self, url: str, username: str, password: str) -> None:
        """Fetch remote playlists in a background thread."""
        work = _LoadPlaylistsWork(url, username, password)
        work.signals.loaded.connect(self.playlistsLoaded.emit)
        work.signals.error.connect(self.error.emit)
        self._pool.start(work)

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
                SubsonicSyncResult(playlists_synced=0, tracks_matched=0, tracks_unmatched=0)
            )
            return

        self._active_workspace = workspace
        self.syncStarted.emit()
        track_index = index_library_tracks(workspace.tracks)
        client = SubsonicClient(url, username, password)
        work = _SyncPlaylistsWork(client, mappings, track_index)
        work.signals.matched.connect(self._apply_sync_results)
        work.signals.error.connect(self.error.emit)
        self._pool.start(work)

    def _apply_sync_results(
        self,
        matched_items: tuple[tuple[SubsonicPlaylistMapping, tuple[int, ...], int], ...],
        errors: tuple[str, ...],
    ) -> None:
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
                    else:  # MERGE
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
