"""Detect an iPod's mounted filesystem and resolve its iTunesDB OS flag."""

from __future__ import annotations

import ctypes
import logging
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ITUNESDB_PLATFORM_MAC = 1
ITUNESDB_PLATFORM_WINDOWS = 2

_MAC_FILESYSTEMS = frozenset({"apfs", "hfs", "hfs+", "hfsplus", "hfsx"})
_WINDOWS_FILESYSTEMS = frozenset({
    "exfat",
    "fat",
    "fat16",
    "fat32",
    "msdos",
    "msdosfs",
    "ntfs",
    "vfat",
})


@dataclass(frozen=True, slots=True)
class ITunesDBPlatformResolution:
    """Selected MHBD platform flag and the evidence behind it."""

    flag: int
    source: str
    filesystem_type: str
    inferred_flag: int | None
    reference_platform: int | None
    mismatch: bool


def detect_filesystem_type(mount_path: str | Path) -> str:
    """Return the actual mounted filesystem type, or an empty string."""
    path = str(mount_path)
    if sys.platform == "win32":
        return _detect_windows_filesystem(path)
    if sys.platform == "darwin":
        return _detect_macos_filesystem(path)
    if sys.platform.startswith("linux"):
        return _detect_linux_filesystem(path)
    return ""


def filesystem_itunesdb_platform(filesystem_type: str) -> int | None:
    """Infer an MHBD OS platform from a mounted filesystem type."""
    normalized = _normalize_filesystem_type(filesystem_type)
    if normalized in _MAC_FILESYSTEMS:
        return ITUNESDB_PLATFORM_MAC
    if normalized in _WINDOWS_FILESYSTEMS:
        return ITUNESDB_PLATFORM_WINDOWS
    return None


def resolve_itunesdb_platform(
    *,
    filesystem_type: str,
    reference_platform: int | None,
) -> ITunesDBPlatformResolution:
    """Preserve a valid DB flag, using the filesystem only as fallback."""
    normalized_fs = _normalize_filesystem_type(filesystem_type)
    inferred = filesystem_itunesdb_platform(normalized_fs)
    reference = (
        reference_platform
        if reference_platform in (ITUNESDB_PLATFORM_MAC, ITUNESDB_PLATFORM_WINDOWS)
        else None
    )

    if reference is not None:
        flag = reference
        source = "existing_database"
    elif inferred is not None:
        flag = inferred
        source = "filesystem"
    else:
        flag = ITUNESDB_PLATFORM_WINDOWS
        source = "default"

    return ITunesDBPlatformResolution(
        flag=flag,
        source=source,
        filesystem_type=normalized_fs,
        inferred_flag=inferred,
        reference_platform=reference,
        mismatch=(reference is not None and inferred is not None and reference != inferred),
    )


def _normalize_filesystem_type(value: str) -> str:
    return str(value or "").strip().casefold()


def _detect_linux_filesystem(mount_path: str) -> str:
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "--target", mount_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if proc.returncode == 0:
            value = _normalize_filesystem_type(proc.stdout.splitlines()[0])
            if value:
                return value
    except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
        pass

    def _decode_mount_field(value: str) -> str:
        return re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            value,
        )

    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as mounts:
            for line in mounts:
                parts = line.split()
                if len(parts) >= 3 and _decode_mount_field(parts[1]) == mount_path:
                    return _normalize_filesystem_type(parts[2])
    except OSError as exc:
        logger.debug("Could not read Linux mount table for %s: %s", mount_path, exc)
    return ""


def _detect_macos_filesystem(mount_path: str) -> str:
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", mount_path],
            capture_output=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return ""
        info = plistlib.loads(proc.stdout)
        if not isinstance(info, dict):
            return ""
        for key in ("FilesystemType", "FilesystemName", "FilesystemPersonality"):
            value = _normalize_filesystem_type(info.get(key, ""))
            if value:
                return value
    except (FileNotFoundError, subprocess.TimeoutExpired, plistlib.InvalidFileException) as exc:
        logger.debug("Could not detect macOS filesystem for %s: %s", mount_path, exc)
    return ""


def _detect_windows_filesystem(mount_path: str) -> str:
    absolute = os.path.abspath(mount_path)
    drive, _tail = os.path.splitdrive(absolute)
    root = f"{drive}\\" if drive else str(Path(absolute).anchor or absolute)
    filesystem_name = ctypes.create_unicode_buffer(256)
    try:
        get_volume_information = ctypes.windll.kernel32.GetVolumeInformationW  # type: ignore[attr-defined]
        success = get_volume_information(
            root,
            None,
            0,
            None,
            None,
            None,
            filesystem_name,
            len(filesystem_name),
        )
    except (AttributeError, OSError) as exc:
        logger.debug("Could not detect Windows filesystem for %s: %s", mount_path, exc)
        return ""
    return _normalize_filesystem_type(filesystem_name.value) if success else ""
