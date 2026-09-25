"""Private containment, file-kind, fingerprint, and durability helpers."""

from __future__ import annotations

import hashlib
import os
import stat
from typing import TYPE_CHECKING, BinaryIO

from storage.errors import (
    ConcurrentModificationError,
    DevicePathNotFoundError,
    InvalidDevicePathError,
    StorageOperationError,
    UnsafeFilesystemPathError,
)
from storage.models import FileFingerprint, StorageCapabilities

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from storage.paths import DevicePath

COPY_CHUNK_SIZE = 1024 * 1024
_WINDOWS_PATH_SEMANTICS = os.name == "nt"
_WINDOWS_INVALID_PATH_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_PATH_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_FAT_FILESYSTEMS = frozenset(
    {"exfat", "fat", "fat16", "fat32", "msdos", "msdosfs", "vfat"}
)
_HFS_FILESYSTEMS = frozenset({"hfs", "hfs+", "hfsplus", "hfsx"})


def modified_time_matches(actual: int, expected: int, filesystem_type: str) -> bool:
    """Compare a represented modification time using filesystem precision."""

    normalized = filesystem_type.casefold()
    tolerance = (
        2_000_000_000
        if normalized in _FAT_FILESYSTEMS
        else 1_000_000_000
        if normalized in _HFS_FILESYSTEMS
        else 1_000_000
    )
    return abs(actual - expected) <= tolerance


def resolve_device_path(
    root: Path,
    path: DevicePath,
    capabilities: StorageCapabilities,
    *,
    require_leaf: bool = False,
) -> Path:
    """Resolve a Device Path while rejecting every existing link component."""

    _validate_root(root)
    if _WINDOWS_PATH_SEMANTICS:
        for component in path.parts:
            stem = component.split(".", maxsplit=1)[0].casefold()
            if (
                component.endswith((" ", "."))
                or stem in _WINDOWS_RESERVED_PATH_NAMES
                or any(
                    ord(character) < 32 or character in _WINDOWS_INVALID_PATH_CHARACTERS
                    for character in component
                )
            ):
                raise InvalidDevicePathError(
                    f"A Device Path component is not representable on Windows: "
                    f"{component!r}"
                )
    component_limit = capabilities.max_component_length
    if component_limit is not None:
        for component in path.parts:
            if len(os.fsencode(component)) > component_limit:
                raise UnsafeFilesystemPathError(
                    f"Device Path component exceeds the filesystem limit: {component!r}"
                )

    current = root
    for index, component in enumerate(path.parts):
        current = current / component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError as error:
            if require_leaf or index < len(path.parts) - 1:
                if index < len(path.parts) - 1:
                    continue
                raise DevicePathNotFoundError(
                    f"Device Path does not exist: {path}"
                ) from error
            continue
        except OSError as error:
            raise StorageOperationError(
                f"Could not safely inspect Device Path {path}: {error}"
            ) from error
        if is_link_or_reparse(metadata):
            raise UnsafeFilesystemPathError(
                f"Device Path contains a symbolic link or reparse point: {path}"
            )
        if index < len(path.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise UnsafeFilesystemPathError(
                f"An intermediate Device Path component is not a directory: {path}"
            )

    resolved = current.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise UnsafeFilesystemPathError(f"Device Path escapes its Volume: {path}")
    return current


def open_read_no_follow(path: Path) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise StorageOperationError(
            f"Could not open device file {path.name}: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise UnsafeFilesystemPathError(
                f"Device Path does not name a regular file: {path.name}"
            )
        file = os.fdopen(descriptor, "rb")
        descriptor = -1
        return file
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_and_fingerprint(
    path: Path,
    *,
    collect_data: bool,
    max_bytes: int | None,
    assert_active: Callable[[], None],
) -> tuple[bytes, FileFingerprint]:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with open_read_no_follow(path) as source:
        before = os.fstat(source.fileno())
        while True:
            assert_active()
            chunk = source.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            if collect_data:
                chunks.append(chunk)
            if max_bytes is not None and source.tell() > max_bytes:
                raise StorageOperationError(
                    f"Device file exceeds the allowed read size of {max_bytes} bytes"
                )
        after = os.fstat(source.fileno())
    if _stat_identity(before) != _stat_identity(after):
        raise ConcurrentModificationError(
            f"Device file changed while it was being read: {path.name}"
        )
    return b"".join(chunks), fingerprint_from_stat(after, digest.hexdigest())


def fingerprint_from_stat(
    metadata: os.stat_result,
    sha256: str,
) -> FileFingerprint:
    return FileFingerprint(
        size=int(metadata.st_size),
        modified_ns=int(metadata.st_mtime_ns),
        device=int(metadata.st_dev),
        inode=int(metadata.st_ino),
        sha256=sha256,
    )


def flush_written_file(file: BinaryIO) -> None:
    file.flush()
    os.fsync(file.fileno())


def flush_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def allocated_size(logical_size: int, allocation_unit: int | None) -> int:
    size = max(0, logical_size)
    unit = max(0, allocation_unit or 0)
    if size == 0 or unit <= 1:
        return size
    return ((size + unit - 1) // unit) * unit


def is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _validate_root(root: Path) -> None:
    try:
        metadata = os.lstat(root)
    except OSError as error:
        raise StorageOperationError(
            f"Could not inspect the Volume root: {error}"
        ) from error
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeFilesystemPathError(
            "The Filesystem Session root is not a safe directory"
        )


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )
