"""Read the mounted Btrfs identity without opening or mutating block devices."""

from __future__ import annotations

import os
import platform
import struct
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from storage.errors import MountInspectionError

if TYPE_CHECKING:
    from pathlib import Path

# linux/btrfs.h: _IOR(0x94, 31, struct btrfs_ioctl_fs_info_args).
# The fixed-size UAPI structure is 1024 bytes, starting with two u64s and a UUID.
_FS_INFO_SIZE = 1024
_FS_INFO = 0x8400941F
_GENERIC_IOCTL_ARCHES = {"x86_64", "i386", "i686", "aarch64", "armv7l", "riscv64"}


class _Ioctl(Protocol):
    def __call__(
        self,
        descriptor: int,
        operation: int,
        argument: bytearray,
        /,
    ) -> int: ...


@dataclass(frozen=True)
class BtrfsFilesystemInfo:
    fsid: str
    device_count: int
    max_device_id: int


def read_filesystem_info(
    path: Path, device_number: str | None = None
) -> BtrfsFilesystemInfo:
    """Bind a read-only ioctl to the directory and captured mount device number."""
    if (
        sys.platform != "linux"
        or platform.machine().lower() not in _GENERIC_IOCTL_ARCHES
    ):
        raise MountInspectionError(
            "Btrfs inspection requires a supported Linux ioctl ABI"
        )
    ioctl = cast("_Ioctl", vars(__import__("fcntl"))["ioctl"])
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if device_number is not None and (
            f"{os.major(before.st_dev)}:{os.minor(before.st_dev)}" != device_number
        ):
            raise MountInspectionError("Btrfs mount changed before inspection")
        buffer = bytearray(_FS_INFO_SIZE)
        ioctl(descriptor, _FS_INFO, buffer)
        max_id, count, fsid = struct.unpack_from("=QQ16s", buffer)
        if count < 1 or max_id < count or not any(fsid):
            raise MountInspectionError("Incomplete Btrfs filesystem information")
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise MountInspectionError("Btrfs directory changed during inspection")
        return BtrfsFilesystemInfo(str(UUID(bytes=fsid)), count, max_id)
    finally:
        os.close(descriptor)
