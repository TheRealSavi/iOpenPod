"""Capture categorized folder sizes through an identity-bound Storage session."""

from collections.abc import Callable

from storage import (
    DeviceEntryKind,
    DevicePath,
    FilesystemSession,
    StorageOperationError,
)

GAME_STORAGE_ROOTS = (
    DevicePath("iPod_Control/Games_RO"),
    DevicePath("iPod_Control/GameData_RW"),
    DevicePath("iPod_Control/GameStats_WO"),
)
ALBUM_ARTWORK_STORAGE_ROOTS = (DevicePath("iPod_Control/Artwork"),)
_MAX_ENTRIES = 100_000


def is_folder_storage_location(location: str, roots: tuple[DevicePath, ...]) -> bool:
    """Recognize descriptive locations without granting filesystem authority."""
    key = location.replace("\\", "/").replace(":", "/").strip("/").casefold()
    return any(key.startswith(f"{str(root).casefold()}/") for root in roots)


def capture_folder_storage_bytes(
    session: FilesystemSession,
    roots: tuple[DevicePath, ...],
    checkpoint: Callable[[], None],
) -> int:
    """Sum all regular files, including databases and unrecognized contents.

    Directory sizes and links are excluded; file contents are never opened.
    Enumeration is bounded and cancellation remains owned by the caller.
    """
    total = 0
    count = 0
    pending: list[DevicePath] = []
    for root in roots:
        checkpoint()
        if session.exists(root):
            pending.append(root)
    while pending:
        checkpoint()
        for entry in session.list_directory(pending.pop()):
            checkpoint()
            count += 1
            if count > _MAX_ENTRIES:
                raise StorageOperationError("Folder storage exceeds the entry limit.")
            if entry.kind is DeviceEntryKind.DIRECTORY:
                pending.append(entry.path)
            elif entry.kind is DeviceEntryKind.FILE:
                total += max(0, entry.size)
    return total
