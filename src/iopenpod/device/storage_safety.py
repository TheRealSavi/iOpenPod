"""Filesystem-aware size and allocation checks for device writes."""

from __future__ import annotations

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
