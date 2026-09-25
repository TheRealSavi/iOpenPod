"""Shared mounted-filesystem facts for native platform adapters."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Protocol, cast

from storage.models import StorageCapabilities

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_MAX_FILE_SIZE_BYTES = {
    "fat": 2 * 1024**3 - 1,
    "fat16": 2 * 1024**3 - 1,
    "fat32": 4 * 1024**3 - 1,
    "msdos": 4 * 1024**3 - 1,
    "msdosfs": 4 * 1024**3 - 1,
    "vfat": 4 * 1024**3 - 1,
}
_CASE_INSENSITIVE_FILESYSTEMS = frozenset(
    {"exfat", "fat", "fat16", "fat32", "msdos", "msdosfs", "ntfs", "vfat"}
)


class _StatVfsResult(Protocol):
    f_frsize: int
    f_bsize: int


def disk_usage(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


def allocation_unit(path: Path) -> int | None:
    statvfs = vars(os).get("statvfs")
    if not callable(statvfs):
        return None
    try:
        call = cast("Callable[[str], _StatVfsResult]", statvfs)
        result = call(os.fspath(path))
    except OSError:
        return None
    size = int(result.f_frsize or result.f_bsize)
    return size if size > 0 else None


def component_limit(path: Path) -> int | None:
    pathconf = vars(os).get("pathconf")
    if not callable(pathconf):
        return None
    try:
        call = cast("Callable[[str, str], int]", pathconf)
        result = int(call(os.fspath(path), "PC_NAME_MAX"))
    except (OSError, ValueError):
        return None
    return result if result > 0 else None


def capabilities(
    path: Path,
    *,
    filesystem_type: str,
    read_only: bool,
    unsafe_write_reasons: tuple[str, ...] = (),
    known_allocation_unit: int | None = None,
    known_component_limit: int | None = None,
    known_case_sensitive: bool | None = None,
) -> StorageCapabilities:
    normalized = filesystem_type.strip().casefold()
    readable = os.access(path, os.R_OK)
    writable = not read_only and not unsafe_write_reasons and os.access(path, os.W_OK)
    return StorageCapabilities(
        readable=readable,
        writable=writable,
        case_sensitive=(
            known_case_sensitive
            if known_case_sensitive is not None
            else (False if normalized in _CASE_INSENSITIVE_FILESYSTEMS else None)
        ),
        max_file_size_bytes=_MAX_FILE_SIZE_BYTES.get(normalized),
        max_component_length=known_component_limit or component_limit(path),
        allocation_unit_size=known_allocation_unit or allocation_unit(path),
        unsafe_write_reasons=unsafe_write_reasons,
    )
