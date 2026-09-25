"""The file-tree scope shared by Backup capture, verification, and restore."""

from __future__ import annotations

from storage import DeviceEntry, DeviceEntryKind, FilesystemSession

_EXCLUDED_COMPONENTS = frozenset(
    {
        "system volume information",
        "$recycle.bin",
        ".trashes",
        ".fseventsd",
        ".spotlight-v100",
        ".ds_store",
        ".metadata_never_index",
        "thumbs.db",
        "desktop.ini",
        ".iopenpod-trash",
        ".iopenpod-recovery",
    }
)
_EXCLUDED_PREFIXES = ("._", ".iop-")


class UnsupportedBackupEntryError(RuntimeError):
    """A Backup tree contains a link, reparse point, or special file."""


def enumerate_backup_files(session: FilesystemSession) -> tuple[DeviceEntry, ...]:
    """Return the one canonical, safe set of files owned by Backup Snapshots."""

    files: list[DeviceEntry] = []
    pending = list(reversed(session.list_root()))
    while pending:
        entry = pending.pop()
        if _is_excluded(entry):
            continue
        if entry.kind is DeviceEntryKind.DIRECTORY:
            pending.extend(reversed(session.list_directory(entry.path)))
        elif entry.kind is DeviceEntryKind.FILE:
            files.append(entry)
        else:
            raise UnsupportedBackupEntryError(
                f"Unsupported entry in the Backup file tree: {entry.path}"
            )
    return tuple(sorted(files, key=lambda item: item.path.parts))


def _is_excluded(entry: DeviceEntry) -> bool:
    return any(
        part.casefold() in _EXCLUDED_COMPONENTS
        or part.casefold().startswith(_EXCLUDED_PREFIXES)
        for part in entry.path.parts
    )


__all__ = ["UnsupportedBackupEntryError", "enumerate_backup_files"]
