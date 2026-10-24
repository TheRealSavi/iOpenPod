"""Capture optional native Genius browsing evidence through Storage."""

from dataclasses import replace

from iOpenPod.app.services import library_resources
from iPodDB.library import LibrarySnapshot, PlaybackSidecar
from iPodDB.library.genius import GeniusBrowse, GeniusBrowseIssue, project_genius_browse
from storage import DevicePath, FilesystemSession, StorageError

_LIBRARY = DevicePath("iPod_Control/iTunes/iTunes Library.itlp/Library.itdb")
_READ_LIMIT = 1024 * 1024 * 1024


def capture_genius_browse(
    session: FilesystemSession,
    snapshot: LibrarySnapshot,
    *,
    sqlite: bool,
    sidecars: tuple[PlaybackSidecar, ...] | None = None,
    sqlite_library: bytes | None = None,
) -> GeniusBrowse:
    """Optional display evidence never changes or becomes the editable Library."""
    issues: list[GeniusBrowseIssue] = []
    if sidecars is None:
        try:
            sidecars, _ = library_resources.load_sidecars(session)
        except (StorageError, ValueError) as error:
            if not session.is_active:
                raise
            sidecars = ()
            issues.append(GeniusBrowseIssue("sidecars.unreadable", str(error)))
    library = sqlite_library
    if sqlite and library is None:
        try:
            if session.exists(_LIBRARY):
                captured = session.read_snapshot(_LIBRARY, max_bytes=_READ_LIMIT)
                if session.fingerprint(_LIBRARY) == captured.fingerprint:
                    library = captured.data
                else:
                    issues.append(
                        GeniusBrowseIssue(
                            "sqlite.changed",
                            "Genius collections changed while loading. Reload the iPod.",
                        )
                    )
        except StorageError as error:
            if not session.is_active:
                raise
            issues.append(GeniusBrowseIssue("sqlite.unreadable", str(error)))
    browse = project_genius_browse(snapshot, sidecars, sqlite_library=library)
    return replace(browse, issues=(*issues, *browse.issues))
