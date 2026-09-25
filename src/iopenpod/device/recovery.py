"""Linux mount facts used to build conservative iPod recovery guidance."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .filesystem import ITUNESDB_PLATFORM_MAC, filesystem_itunesdb_platform

_FAT_FILESYSTEMS = frozenset({"fat", "fat16", "fat32", "msdos", "msdosfs", "vfat"})


@dataclass(frozen=True, slots=True)
class LinuxMountDetails:
    """Facts reported by Linux for the mount containing an iPod path."""

    mount_point: str
    source: str
    filesystem: str
    options: tuple[str, ...]
    super_options: tuple[str, ...]

    @property
    def is_read_only(self) -> bool:
        return "ro" in self.options or "ro" in self.super_options

    @property
    def summary(self) -> str:
        options = ",".join(self.options)
        return (
            f"{self.source or 'unknown device'} on {self.mount_point} "
            f"({self.filesystem or 'unknown filesystem'}, {options})"
        )


@dataclass(frozen=True, slots=True)
class LinuxFilesystemRecoveryPlan:
    """Structured recovery facts; presentation copy belongs to the GUI."""

    mount_path: str
    source: str
    filesystem: str
    kind: Literal["fat", "exfat", "mac", "ntfs", "unknown"]
    unmount_command: str
    identify_command: str
    checker_command: str


def linux_mount_details(path: str | Path) -> LinuxMountDetails | None:
    """Return the most specific Linux mount containing *path*."""
    if not sys.platform.startswith("linux"):
        return None

    target = os.path.realpath(path)
    best: LinuxMountDetails | None = None
    for mount in _read_linux_mounts():
        mount_point = mount.mount_point.rstrip(os.sep) or os.sep
        if mount_point == os.sep:
            continue
        matches = target == mount_point or target.startswith(mount_point + os.sep)
        if matches and (best is None or len(mount_point) > len(best.mount_point)):
            best = mount
    return best


def linux_filesystem_recovery_plan(
    mount_path: str | Path,
    *,
    filesystem: str = "",
    source: str = "",
) -> LinuxFilesystemRecoveryPlan:
    """Return filesystem-specific, non-writing recovery operations."""
    mount = str(mount_path)
    details = linux_mount_details(mount)
    actual_mount = details.mount_point if details is not None else mount
    actual_filesystem = str(filesystem or (details.filesystem if details else "")).strip().casefold()
    actual_source = str(source or (details.source if details else "")).strip()

    if actual_filesystem in _FAT_FILESYSTEMS:
        kind: Literal["fat", "exfat", "mac", "ntfs", "unknown"] = "fat"
        checker = f"sudo fsck.fat -n {shlex.quote(actual_source)}" if actual_source else ""
    elif actual_filesystem == "exfat":
        kind = "exfat"
        checker = f"sudo fsck.exfat -n {shlex.quote(actual_source)}" if actual_source else ""
    elif filesystem_itunesdb_platform(actual_filesystem) == ITUNESDB_PLATFORM_MAC:
        kind = "mac"
        checker = ""
    elif actual_filesystem == "ntfs":
        kind = "ntfs"
        checker = ""
    else:
        kind = "unknown"
        checker = ""

    quoted_mount = shlex.quote(actual_mount)
    return LinuxFilesystemRecoveryPlan(
        mount_path=actual_mount,
        source=actual_source,
        filesystem=actual_filesystem,
        kind=kind,
        unmount_command=f"sudo umount {quoted_mount}",
        identify_command=f"findmnt -no SOURCE,FSTYPE,OPTIONS --target {quoted_mount}",
        checker_command=checker,
    )


def _read_linux_mounts() -> list[LinuxMountDetails]:
    mounts: list[LinuxMountDetails] = []
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return mounts

    for line in lines:
        parts = line.split()
        if "-" not in parts:
            continue
        separator = parts.index("-")
        if separator + 3 > len(parts):
            continue
        mount_fields = parts[:separator]
        fs_fields = parts[separator + 1 :]
        if len(mount_fields) < 6 or len(fs_fields) < 3:
            continue
        mounts.append(
            LinuxMountDetails(
                mount_point=os.path.realpath(_decode_mount_field(mount_fields[4])),
                options=tuple(mount_fields[5].split(",")),
                filesystem=fs_fields[0],
                source=_decode_mount_field(fs_fields[1]),
                super_options=tuple(fs_fields[2].split(",")),
            )
        )
    return mounts


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )
