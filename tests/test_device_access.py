from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from iopenpod.application import device_access
from iopenpod.device import recovery
from iopenpod.device.recovery import LinuxMountDetails, linux_filesystem_recovery_plan
from iopenpod.device.write_guard import DeviceWriteSafetyError


def test_check_ipod_write_access_accepts_writable_ipod_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    profile = SimpleNamespace()
    monkeypatch.setattr(
        device_access,
        "inspect_device_write_readiness",
        lambda _path: profile,
    )
    monkeypatch.setattr(device_access, "volume_lock_key", lambda _profile: "volume")
    monkeypatch.setattr(
        device_access,
        "DeviceWriteGuard",
        lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        device_access,
        "revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
    )

    result = device_access.check_ipod_write_access(tmp_path)

    assert result.writable
    assert not list((tmp_path / "iPod_Control" / "iTunes").iterdir())


def test_check_ipod_write_access_reports_permission_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    profile = SimpleNamespace()
    monkeypatch.setattr(
        device_access,
        "inspect_device_write_readiness",
        lambda _path: profile,
    )
    monkeypatch.setattr(device_access, "volume_lock_key", lambda _profile: "volume")
    monkeypatch.setattr(
        device_access,
        "DeviceWriteGuard",
        lambda *_args, **_kwargs: nullcontext(),
    )

    monkeypatch.setattr(
        device_access,
        "revalidate_device_write_readiness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DeviceWriteSafetyError("Permission denied")
        ),
    )

    result = device_access.check_ipod_write_access(tmp_path)

    assert not result.writable
    assert result.mount_path == str(tmp_path)
    assert "Permission denied" in result.reason


def test_check_ipod_write_access_reports_linux_read_only_mount(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    mount = LinuxMountDetails(
        mount_point=str(tmp_path),
        source="/dev/sdz1",
        filesystem="vfat",
        options=("ro", "nosuid"),
        super_options=("ro",),
    )
    monkeypatch.setattr(device_access, "linux_mount_details", lambda _path: mount)

    result = device_access.check_ipod_write_access(tmp_path)

    assert not result.writable
    assert result.reason == "mount is read-only"
    assert result.mount == mount
    plan = linux_filesystem_recovery_plan(
        result.mount_path,
        filesystem=mount.filesystem,
        source=mount.source,
    )
    assert plan.kind == "fat"
    assert plan.checker_command == "sudo fsck.fat -n /dev/sdz1"


def test_check_ipod_write_access_sends_hfsplus_to_macos_first_aid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    mount = LinuxMountDetails(
        mount_point=str(tmp_path),
        source="/dev/sdz2",
        filesystem="hfsplus",
        options=("ro", "nosuid"),
        super_options=("ro",),
    )
    monkeypatch.setattr(device_access, "linux_mount_details", lambda _path: mount)

    result = device_access.check_ipod_write_access(tmp_path)

    assert result.writable is False
    assert result.mount == mount
    plan = linux_filesystem_recovery_plan(
        result.mount_path,
        filesystem=mount.filesystem,
        source=mount.source,
    )
    assert plan.kind == "mac"
    assert not plan.checker_command


def test_recovery_plan_uses_the_detected_mount_source_and_filesystem(
    monkeypatch,
) -> None:
    mount = LinuxMountDetails(
        mount_point="/media/user/IPOD",
        source="/dev/sdz1",
        filesystem="vfat",
        options=("ro",),
        super_options=("ro",),
    )
    monkeypatch.setattr(recovery, "linux_mount_details", lambda _path: mount)

    plan = recovery.linux_filesystem_recovery_plan("/media/user/IPOD")

    assert plan.mount_path == "/media/user/IPOD"
    assert plan.source == "/dev/sdz1"
    assert plan.filesystem == "vfat"
    assert plan.unmount_command == "sudo umount /media/user/IPOD"
    assert plan.checker_command == "sudo fsck.fat -n /dev/sdz1"
