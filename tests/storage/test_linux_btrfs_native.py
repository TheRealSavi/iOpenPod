"""Native UAPI and mounted Btrfs coverage; application inspection is unprivileged."""

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

from storage import MountInspectionError
from storage.platform.linux import LinuxPlatformAdapter, parse_mountinfo
from storage.platform.linux_btrfs import BtrfsFilesystemInfo, read_filesystem_info

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux UAPI")

_FSID = "12345678-1234-5678-9abc-123456789abc"


def _mount_id(path: Path) -> str:
    records = parse_mountinfo(Path("/proc/self/mountinfo").read_text())
    return max(
        (r for r in reversed(records) if path.is_relative_to(r.mount_point)),
        key=lambda r: len(str(r.mount_point)),
    ).mount_id


def test_btrfs_ioctl_matches_installed_linux_headers(tmp_path: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler required for native UAPI layout validation")
    binary = tmp_path / "btrfs-uapi"
    source = """
#include <linux/btrfs.h>
#include <stddef.h>
#include <stdio.h>
int main(void) {
    printf("%lu %zu %zu %zu %zu\\n", (unsigned long) BTRFS_IOC_FS_INFO,
           sizeof(struct btrfs_ioctl_fs_info_args),
           offsetof(struct btrfs_ioctl_fs_info_args, max_id),
           offsetof(struct btrfs_ioctl_fs_info_args, num_devices),
           offsetof(struct btrfs_ioctl_fs_info_args, fsid));
}
"""
    subprocess.run(
        [compiler, "-x", "c", "-o", str(binary), "-"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    result = subprocess.run([str(binary)], text=True, capture_output=True, check=True)
    assert [int(value) for value in result.stdout.split()] == [
        0x8400941F,
        1024,
        0,
        8,
        16,
    ]


@pytest.mark.parametrize(
    "failure", [None, "ioctl", "empty", "count", "id", "mount", "path"]
)
def test_btrfs_ioctl_validates_identity_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux")
    import fcntl

    directory = tmp_path / "recovery"
    directory.mkdir()
    opened: list[int] = []
    real_open = os.open

    def opened_directory(path: Path, flags: int) -> int:
        assert path == directory
        assert flags & os.O_DIRECTORY
        assert flags & os.O_NOFOLLOW
        assert not flags & (os.O_WRONLY | os.O_RDWR)
        descriptor = real_open(path, flags)
        opened.append(descriptor)
        return descriptor

    def ioctl(descriptor: int, operation: int, buffer: bytearray) -> int:
        assert descriptor == opened[-1]
        assert operation == 0x8400941F
        assert buffer == bytearray(1024)
        if failure == "ioctl":
            raise PermissionError("fixture ioctl refused")
        struct.pack_into(
            "=QQ16s",
            buffer,
            0,
            0 if failure == "id" else 17,
            0 if failure == "count" else 2,
            bytes(16) if failure == "empty" else UUID(_FSID).bytes,
        )
        if failure == "path":
            directory.rename(tmp_path / "old")
            directory.mkdir()
        return 0

    monkeypatch.setattr(os, "open", opened_directory)
    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    mount_id = "0" if failure == "mount" else _mount_id(directory)
    if failure:
        with pytest.raises((MountInspectionError, PermissionError)):
            read_filesystem_info(directory, mount_id)
    else:
        assert read_filesystem_info(directory, mount_id) == BtrfsFilesystemInfo(
            _FSID, 2, 17
        )
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_live_btrfs_membership_and_loop_rejection() -> None:
    """CI supplies an isolated, mounted two-device Btrfs image and subvolume alias."""
    if sys.platform != "linux":
        pytest.skip("requires Linux")
    location = os.environ.get("IOPENPOD_TEST_BTRFS")
    if not location:
        pytest.skip("requires the disposable Btrfs fixture from the Linux Health job")
    assert os.geteuid() != 0, "Application inspection must run without root privileges"
    root = Path(location)
    records = parse_mountinfo(Path("/proc/self/mountinfo").read_text())
    snapshots: list[BtrfsFilesystemInfo] = []
    for path in (root / "mounted", root / "mounted/home", root / "alias"):
        record = max(
            (r for r in reversed(records) if path.is_relative_to(r.mount_point)),
            key=lambda r: len(str(r.mount_point)),
        )
        assert record.filesystem_type == "btrfs"
        info = read_filesystem_info(path, record.mount_id)
        snapshots.append(info)
        assert info.device_count == 2
        assert info.max_device_id == 2
        sysfs = Path("/sys/fs/btrfs") / info.fsid
        assert sorted(p.name for p in (sysfs / "devinfo").iterdir()) == ["1", "2"]
        assert len(tuple((sysfs / "devices").iterdir())) == 2
        for member in (sysfs / "devinfo").iterdir():
            assert (member / "fsid").read_text().strip() == info.fsid
        # Real kernel membership passes; its loop leaves remain deliberately refused.
        with pytest.raises(
            MountInspectionError, match="Unsupported Linux block backing"
        ):
            LinuxPlatformAdapter().paths_share_physical_device(path, path)
    assert snapshots[0] == snapshots[1] == snapshots[2]
