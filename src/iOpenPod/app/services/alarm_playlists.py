"""Capture Nano 5's native Alarm Playlist sources through Storage."""

from collections.abc import Callable
from dataclasses import dataclass

from iOpenPod.app.services.library_resources import sqlite_database_path
from iPodDB.library import AlarmPlaylistCatalog, project_sqlite_alarm_playlists
from storage import FilePrecondition, FilesystemSession, StorageError


@dataclass(frozen=True, slots=True)
class CapturedAlarmPlaylists:
    catalog: AlarmPlaylistCatalog
    dependencies: tuple[FilePrecondition, ...] = ()


def capture_sqlite_alarm_playlists(
    session: FilesystemSession, checkpoint: Callable[[], None]
) -> CapturedAlarmPlaylists:
    captured: list[bytes] = []
    dependencies: list[FilePrecondition] = []
    try:
        for name in ("Library.itdb", "Dynamic.itdb"):
            checkpoint()
            path = sqlite_database_path(name)
            source = session.read_snapshot(path, max_bytes=2 * 1024 * 1024 * 1024)
            captured.append(source.data)
            dependencies.append(FilePrecondition(path, source.fingerprint))
    except (StorageError, ValueError) as error:
        if not session.is_active:
            raise
        return CapturedAlarmPlaylists(
            AlarmPlaylistCatalog(
                issues=(f"Alarm Playlists: {error}",), has_master=False
            )
        )
    return CapturedAlarmPlaylists(
        project_sqlite_alarm_playlists(*captured), tuple(dependencies)
    )
