"""Qt controller coordinating Subsonic server network tasks in background threads."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iPodDB.library import PlaylistKind

from .client import SubsonicClient, SubsonicConnectionError
from .credentials import SubsonicCredentialStore, SystemSubsonicCredentialStore
from .models import (
    SubsonicPlaylist,
    SubsonicPlaylistMapping,
    SubsonicSong,
    SubsonicSyncMode,
    SubsonicSyncResult,
    SubsonicSyncScope,
)
from .sync import index_library_tracks, normalize_match_key

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.media.importing import ImportedSong
    from iOpenPod.app.models.device import ActiveIPod

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
    matched = Signal(object, object, object)
    error = Signal(str)


class _SyncPlaylistsWork(QRunnable):
    def __init__(
        self,
        client: SubsonicClient,
        mappings: tuple[SubsonicPlaylistMapping, ...],
        track_index: dict[tuple[str, str], int],
        scope: SubsonicSyncScope,
        cache_dir: Path,
    ) -> None:
        super().__init__()
        self.client = client
        self.mappings = mappings
        self.track_index = track_index
        self.scope = scope
        self.cache_dir = cache_dir
        self.cancelled = threading.Event()
        self.signals = _SyncSignals()

    def run(self) -> None:
        try:
            matched_playlists: list[
                tuple[SubsonicPlaylistMapping, list[tuple[str, str]]]
            ] = []
            downloaded: dict[tuple[str, str], tuple[SubsonicSong, Path]] = {}
            errors: list[str] = []

            self.cache_dir.mkdir(parents=True, exist_ok=True)

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

                playlist_keys: list[tuple[str, str]] = []
                for song in entries:
                    if self.cancelled.is_set():
                        return
                    key = normalize_match_key(song.title, song.artist)
                    if key in self.track_index:
                        playlist_keys.append(key)
                    elif self.scope == SubsonicSyncScope.ALL_SONGS:
                        dest = self.cache_dir / f"{song.song_id}.mp3"
                        try:
                            if not dest.exists() or dest.stat().st_size == 0:
                                self.client.download_track(song.song_id, str(dest))
                            downloaded[key] = (song, dest)
                            playlist_keys.append(key)
                        except Exception as exc:
                            logger.warning(
                                "Failed to download Subsonic track %s: %s",
                                song.title,
                                exc,
                            )

                matched_playlists.append((mapping, playlist_keys))

            if self.cancelled.is_set():
                return
            self.signals.matched.emit(
                tuple(matched_playlists),
                tuple(downloaded.values()),
                tuple(errors),
            )
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
        self._active_ipod: ActiveIPod | None = None
        self._active_track_index: dict[tuple[str, str], int] = {}
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
        *,
        scope: SubsonicSyncScope = SubsonicSyncScope.PLAYLISTS_ONLY,
        active_ipod: ActiveIPod | None = None,
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
        self._active_ipod = active_ipod
        self._active_track_index = index_library_tracks(workspace.tracks)
        self.syncStarted.emit()
        client = SubsonicClient(url, username, password)
        cache_dir = Path(tempfile.gettempdir()) / "iopenpod_subsonic"
        work = _SyncPlaylistsWork(
            client, mappings, self._active_track_index, scope, cache_dir
        )
        self._sync_job = work
        work.signals.matched.connect(
            self._apply_sync_results, Qt.ConnectionType.QueuedConnection
        )
        work.signals.error.connect(
            self._handle_sync_error, Qt.ConnectionType.QueuedConnection
        )
        self._pool.start(work)

    @Slot(object, object, object)
    def _apply_sync_results(
        self,
        matched_playlists: tuple[
            tuple[SubsonicPlaylistMapping, list[tuple[str, str]]], ...
        ],
        downloaded_tracks: tuple[tuple[SubsonicSong, Path], ...],
        errors: tuple[str, ...],
    ) -> None:
        self._sync_job = None
        workspace = self._active_workspace
        active = self._active_ipod
        if workspace is None:
            self.error.emit("Library workspace was disconnected during sync.")
            return

        track_index = dict(self._active_track_index)
        songs_downloaded = 0
        all_errors = list(errors)

        if downloaded_tracks and active is not None:
            try:
                from iOpenPod.app.media.importing import MusicImporter, relocate_song
                from iOpenPod.app.media.music_paths import MusicPathAllocator
                from storage import HostPath

                importer = MusicImporter()
                occupied = tuple(
                    track.metadata.location
                    for track in (*active.library.tracks, *workspace.tracks)
                )
                allocator = MusicPathAllocator(
                    active.profile.capabilities.database.music_directory_count,
                    occupied,
                )
                imported_songs: list[ImportedSong] = []
                song_key_to_loc: dict[tuple[str, str], str] = {}
                for sub_song, path in downloaded_tracks:
                    try:
                        song = importer.inspect(
                            HostPath(path),
                            active.profile,
                            checkpoint=lambda: None,
                        )
                        ext = path.suffix.removeprefix(".") or "mp3"
                        dest = allocator.allocate(ext)
                        relocated = relocate_song(song, dest)
                        imported_songs.append(relocated)
                        song_key_to_loc[
                            normalize_match_key(sub_song.title, sub_song.artist)
                        ] = dest
                    except Exception as exc:
                        logger.warning(
                            "Could not inspect downloaded song %s: %s",
                            sub_song.title,
                            exc,
                        )

                if imported_songs:
                    workspace.add_songs(tuple(imported_songs), workspace.edit_revision)
                    songs_downloaded = len(imported_songs)
                    loc_to_id = {
                        t.metadata.location: t.track_id for t in workspace.tracks
                    }
                    for key, loc in song_key_to_loc.items():
                        if loc in loc_to_id:
                            track_index[key] = loc_to_id[loc]
            except Exception as exc:
                err_msg = f"Failed to import downloaded songs into iPod library: {exc}"
                logger.error(err_msg, exc_info=True)
                all_errors.append(err_msg)

        playlists_synced = 0
        total_matched = 0
        total_unmatched = 0

        for mapping, keys in matched_playlists:
            matched_ids: list[int] = []
            for key in keys:
                tid = track_index.get(key)
                if tid is not None:
                    matched_ids.append(tid)
                else:
                    total_unmatched += 1

            total_matched += len(matched_ids)

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
                        track_ids=tuple(matched_ids),
                    )
                    playlists_synced += 1
                else:
                    existing = workspace.playlist(mapping.target_ipod_id)
                    if existing is None:
                        workspace.create(
                            kind=PlaylistKind.PLAYLIST,
                            name=mapping.subsonic_name,
                            track_ids=tuple(matched_ids),
                        )
                        playlists_synced += 1
                    elif mapping.mode == SubsonicSyncMode.OVERWRITE:
                        workspace.set_tracks(
                            mapping.target_ipod_id, tuple(matched_ids)
                        )
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
            songs_downloaded=songs_downloaded,
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
