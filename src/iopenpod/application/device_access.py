"""Device mount access checks used before iOpenPod starts working with an iPod."""

from __future__ import annotations

import errno
import os
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeviceWriteAccessResult:
    writable: bool
    message: str = ""


@dataclass(frozen=True)
class _LinuxMountInfo:
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


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _read_linux_mounts() -> list[_LinuxMountInfo]:
    mounts: list[_LinuxMountInfo] = []
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
            _LinuxMountInfo(
                mount_point=os.path.realpath(_decode_mount_field(mount_fields[4])),
                options=tuple(mount_fields[5].split(",")),
                filesystem=fs_fields[0],
                source=_decode_mount_field(fs_fields[1]),
                super_options=tuple(fs_fields[2].split(",")),
            )
        )
    return mounts


def _linux_mount_for_path(path: Path) -> _LinuxMountInfo | None:
    if sys.platform != "linux":
        return None
    target = os.path.realpath(path)
    best: _LinuxMountInfo | None = None
    for mount in _read_linux_mounts():
        mount_point = mount.mount_point.rstrip(os.sep) or os.sep
        if mount_point == os.sep:
            matches = target.startswith(os.sep)
        else:
            matches = target == mount_point or target.startswith(mount_point + os.sep)
        if matches:
            if best is None or len(mount_point) > len(best.mount_point):
                best = mount
    return best


def _permission_help(ipod_path: Path, reason: str, mount: _LinuxMountInfo | None) -> str:
    mount_path = str(ipod_path)
    quoted_mount = shlex.quote(mount_path)
    lines = [
        "iOpenPod cannot use this iPod because it is not writable.",
        "",
        f"Mount path: {mount_path}",
    ]
    if mount is not None:
        lines.append(f"Mount: {mount.summary}")
    lines.extend(
        [
            f"System error: {reason}",
            "",
            "On Linux, reconnect the iPod. If it still mounts read-only, try:",
            f"  sudo mount -o remount,rw {quoted_mount}",
            "",
            "If the FAT filesystem is dirty, unmount it before repairing it:",
            f"  sudo umount {quoted_mount}",
            "  sudo fsck.vfat -a /dev/sdXN",
            "",
            "Replace /dev/sdXN with the iPod partition. Do not run fsck while "
            "the iPod is mounted.",
        ]
    )
    return "\n".join(lines)


def check_ipod_write_access(ipod_path: str | Path) -> DeviceWriteAccessResult:
    """Create and remove a tiny probe file to verify iPod write access."""

    root = Path(ipod_path)
    probe_dir = root / "iPod_Control" / "iTunes"
    mount = _linux_mount_for_path(root)
    if mount is not None and mount.is_read_only:
        return DeviceWriteAccessResult(
            False,
            _permission_help(root, "mount is read-only", mount),
        )

    if not probe_dir.is_dir():
        return DeviceWriteAccessResult(
            False,
            _permission_help(root, f"{probe_dir} does not exist", mount),
        )

    fd: int | None = None
    probe_path = ""
    try:
        fd, probe_path = tempfile.mkstemp(
            prefix=".iOpenPod_write_test_",
            dir=str(probe_dir),
        )
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EROFS):
            reason = str(exc).strip() or exc.__class__.__name__
            return DeviceWriteAccessResult(False, _permission_help(root, reason, mount))
        reason = str(exc).strip() or exc.__class__.__name__
        return DeviceWriteAccessResult(False, _permission_help(root, reason, mount))
    finally:
        if fd is not None:
            os.close(fd)

    try:
        os.unlink(probe_path)
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        return DeviceWriteAccessResult(False, _permission_help(root, reason, mount))

    return DeviceWriteAccessResult(True)
