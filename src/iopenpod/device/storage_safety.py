"""Filesystem-aware size and allocation checks for device writes."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from .write_guard import DeviceWriteSafetyError


class FileSizeLimitError(DeviceWriteSafetyError):
    """Raised before a file exceeds a device or filesystem size limit."""


def allocated_size(logical_size: int, allocation_unit_size: int | None) -> int:
    """Return the conservative on-disk bytes used by one logical file."""
    size = max(0, int(logical_size or 0))
    unit = max(0, int(allocation_unit_size or 0))
    if size == 0 or unit <= 1:
        return size
    return ((size + unit - 1) // unit) * unit


def existing_file_allocated_size(
    path: str | Path,
    allocation_unit_size: int | None,
) -> int:
    """Return bytes that deleting an existing file can safely be assumed to free.

    Sparse and compressed files can occupy far less space than their logical
    length. When the host cannot report allocation, return zero rather than
    over-promising space to a destructive restore preflight.
    """
    target = Path(path)
    file_stat = target.stat()
    blocks = getattr(file_stat, "st_blocks", None)
    if isinstance(blocks, int) and blocks >= 0:
        return blocks * 512
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_allocated_size = kernel32.GetCompressedFileSizeW
        get_allocated_size.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        get_allocated_size.restype = ctypes.c_ulong
        high = ctypes.c_ulong(0)
        ctypes.set_last_error(0)
        low = int(get_allocated_size(os.fspath(target), ctypes.byref(high)))
        error = ctypes.get_last_error()
        if low == 0xFFFFFFFF and error:
            raise OSError(error, ctypes.FormatError(error).strip())
        return (int(high.value) << 32) | low
    return 0


def effective_max_file_size_bytes(
    filesystem_limit: int | None,
    device_limit: int | None,
) -> int | None:
    """Return the strictest positive file-size limit supplied by either source."""
    limits = [
        int(limit)
        for limit in (filesystem_limit, device_limit)
        if limit is not None and int(limit) > 0
    ]
    return min(limits) if limits else None


def require_file_size_supported(
    file_size: int,
    *,
    max_file_size_bytes: int | None,
    display_name: str,
) -> None:
    """Raise a user-facing safety error when one file cannot be represented."""
    size = max(0, int(file_size or 0))
    limit = int(max_file_size_bytes or 0)
    if limit <= 0 or size <= limit:
        return
    raise FileSizeLimitError(
        f"{display_name} is {_format_size(size)}, exceeding the "
        f"{_format_size(limit)} maximum supported by this iPod or its "
        "filesystem. iOpenPod stopped before writing the file."
    )


def _format_size(size: int) -> str:
    return f"{size / 1024**3:.1f} GB"
