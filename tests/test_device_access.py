from __future__ import annotations

import errno
from pathlib import Path

from app_core import device_access


def test_check_ipod_write_access_accepts_writable_ipod_root(tmp_path: Path) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)

    result = device_access.check_ipod_write_access(tmp_path)

    assert result.writable
    assert not list((tmp_path / "iPod_Control" / "iTunes").iterdir())


def test_check_ipod_write_access_reports_permission_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)

    def raise_permission_denied(*_args, **_kwargs):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(device_access.tempfile, "mkstemp", raise_permission_denied)

    result = device_access.check_ipod_write_access(tmp_path)

    assert not result.writable
    assert "iOpenPod cannot use this iPod because it is not writable" in result.message
    assert str(tmp_path) in result.message
    assert "Permission denied" in result.message
    assert "mount -o remount,rw" in result.message


def test_check_ipod_write_access_reports_linux_read_only_mount(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    mount = device_access._LinuxMountInfo(
        mount_point=str(tmp_path),
        source="/dev/sdz1",
        filesystem="vfat",
        options=("ro", "nosuid"),
        super_options=("ro",),
    )
    monkeypatch.setattr(device_access, "_linux_mount_for_path", lambda _path: mount)

    result = device_access.check_ipod_write_access(tmp_path)

    assert not result.writable
    assert "mount is read-only" in result.message
    assert "/dev/sdz1" in result.message
    assert "vfat" in result.message
