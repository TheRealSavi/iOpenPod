from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.device import eject
from iopenpod.device.filesystem_profile import FilesystemProfile, VolumeIdentity


def test_virtual_ipod_never_reaches_operating_system_eject(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        eject,
        "_inspect_eject_volume",
        lambda *_args, **_kwargs: pytest.fail("virtual device was inspected as a volume"),
    )
    monkeypatch.setattr(
        eject,
        "_eject_windows",
        lambda *_args, **_kwargs: pytest.fail("OS eject was invoked for virtual device"),
    )

    success, message = eject.eject_ipod(str(tmp_path))

    assert success is True
    assert "no operating-system eject" in message


def _profile(root: Path, *, read_only: bool = False) -> FilesystemProfile:
    return FilesystemProfile(
        mount_path=str(root),
        filesystem_type="vfat",
        reported_volume_format="FAT32",
        mount_source="/dev/sdz1",
        mount_options=("ro" if read_only else "rw",),
        read_only=read_only,
        unsafe_write_reasons=(),
        case_sensitive=False,
        max_file_size_bytes=4 * 1024**3 - 1,
        max_component_length=255,
        allocation_unit_size=4096,
        identity=VolumeIdentity("linux", "8:33", "IPOD", "77"),
        detection_errors=(),
        inspection_path=str(root),
    )


def test_eject_holds_volume_guard_and_allows_read_only_ipod(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control").mkdir()
    profile = _profile(tmp_path, read_only=True)
    events: list[str] = []

    class _Guard:
        def __init__(self, *_args, **kwargs):
            assert kwargs["volume_key"] == "linux|8:33|IPOD|77"
            assert kwargs["track_database_generation"] is False

        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_args):
            events.append("unlock")

    monkeypatch.setattr(eject, "inspect_filesystem_profile", lambda *_a, **_k: profile)
    monkeypatch.setattr(eject, "DeviceWriteGuard", _Guard)
    monkeypatch.setattr(eject.sys, "platform", "linux")
    monkeypatch.setattr(
        eject,
        "_eject_linux",
        lambda _path, **_kwargs: (events.append("eject") or True, "ejected"),
    )

    success, message = eject.eject_ipod(
        str(tmp_path),
        expected_volume_identity_key="linux|8:33|IPOD|77",
    )

    assert success is True
    assert message == "ejected"
    assert events == ["lock", "eject", "unlock"]


def test_eject_refuses_replaced_scan_time_volume(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "iPod_Control").mkdir()
    attempts = 0
    monkeypatch.setattr(
        eject,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: _profile(tmp_path),
    )

    def eject_attempt(_path: Path, **_kwargs) -> tuple[bool, str]:
        nonlocal attempts
        attempts += 1
        return True, "ejected"

    monkeypatch.setattr(eject, "_eject_linux", eject_attempt)
    monkeypatch.setattr(eject.sys, "platform", "linux")

    success, message = eject.eject_ipod(
        str(tmp_path),
        expected_volume_identity_key="linux|8:44|OTHER|88",
    )

    assert success is False
    assert attempts == 0
    assert "different volume" in message.lower()


def test_linux_eject_flush_uses_the_shared_durability_guard(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        eject,
        "flush_filesystem",
        lambda mount_path, *, allow_unavailable: (
            calls.append((str(mount_path), allow_unavailable)) or (True, "flushed")
        ),
    )

    success, message = eject._run_sync("/media/jared/JARED_S IPO")

    assert success is True
    assert message == "flushed"
    assert calls == [("/media/jared/JARED_S IPO", True)]


def test_linux_eject_does_not_dirty_fat_when_safe_unmount_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A failed safe unmount must not become a successful forced eject."""

    state = {
        "mounted": True,
        "fat_dirty": False,
        "unmount_calls": 0,
    }

    monkeypatch.setattr(eject, "_find_block_device", lambda _path: "/dev/sdb1")
    monkeypatch.setattr(
        eject,
        "_linux_path_is_mounted",
        lambda _mount_path, _device=None: state["mounted"],
    )
    monkeypatch.setattr(eject, "_run_sync", lambda _mount_path=None: (True, "flushed"))
    monkeypatch.setattr(
        eject.shutil,
        "which",
        lambda command: "/usr/bin/udisksctl" if command == "udisksctl" else None,
    )

    monkeypatch.setattr(eject, "_wait_for_linux_mount_gone", lambda *_args: False)

    def fake_udisks_unmount(_device: str) -> tuple[bool, str]:
        state["unmount_calls"] += 1
        return False, "target is busy"

    monkeypatch.setattr(eject, "_run_udisks_unmount", fake_udisks_unmount)
    monkeypatch.setattr(
        eject,
        "_run_udisks_poweroff",
        lambda _parent: (True, "Ejected /dev/sdb"),
    )

    success, message = eject._eject_linux(tmp_path)

    assert state["unmount_calls"] == 1
    assert state["fat_dirty"] is False
    assert success is False
    assert "busy" in message.lower()


def test_linux_eject_stops_when_pending_writes_cannot_be_flushed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    unmount_calls = 0

    monkeypatch.setattr(eject, "_find_block_device", lambda _path: "/dev/sdb1")
    monkeypatch.setattr(
        eject,
        "_linux_path_is_mounted",
        lambda _mount_path, _device=None: True,
    )
    monkeypatch.setattr(
        eject,
        "_run_sync",
        lambda _mount_path=None: (False, "filesystem flush timed out"),
    )
    monkeypatch.setattr(
        eject.shutil,
        "which",
        lambda command: "/usr/bin/udisksctl" if command == "udisksctl" else None,
    )
    monkeypatch.setattr(eject, "_wait_for_linux_mount_gone", lambda *_args: True)

    def fake_udisks_eject(_device: str, _mount_path: str) -> tuple[bool, str]:
        nonlocal unmount_calls
        unmount_calls += 1
        return True, "Ejected /dev/sdb"

    monkeypatch.setattr(eject, "_udisks_eject", fake_udisks_eject)

    success, message = eject._eject_linux(tmp_path)

    assert success is False
    assert unmount_calls == 0
    assert "flush" in message.lower()
    assert "timed out" in message.lower()


def test_linux_eject_refuses_when_mount_table_cannot_be_verified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    flush_attempts = 0
    monkeypatch.setattr(eject, "_find_block_device", lambda _path: "/dev/sdb1")
    monkeypatch.setattr(
        eject,
        "_linux_mount_entries",
        lambda: (_ for _ in ()).throw(OSError("mount table unavailable")),
    )

    def flush(_mount_path=None):
        nonlocal flush_attempts
        flush_attempts += 1
        return True, "flushed"

    monkeypatch.setattr(eject, "_run_sync", flush)

    success, message = eject._eject_linux(tmp_path)

    assert success is False
    assert flush_attempts == 0
    assert "mount table" in message.lower()
    assert "did not attempt" in message.lower()


def test_macos_eject_stops_when_full_filesystem_flush_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    eject_attempts: list[list[str]] = []
    monkeypatch.setattr(eject.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        eject,
        "_macos_disk_info",
        lambda _path: (
            {
                "DeviceIdentifier": "disk2s2",
                "ParentWholeDisk": "disk2",
                "MountPoint": str(tmp_path),
            },
            "",
        ),
    )
    monkeypatch.setattr(
        eject,
        "flush_filesystem",
        lambda _path, *, allow_unavailable: (False, "F_FULLFSYNC failed"),
    )
    monkeypatch.setattr(
        eject,
        "_run_command",
        lambda args, **_kwargs: (eject_attempts.append(args) or True, "ejected"),
    )

    success, message = eject._eject_macos(tmp_path)

    assert success is False
    assert "F_FULLFSYNC failed" in message
    assert eject_attempts == []


def test_macos_busy_volume_is_left_mounted_without_forced_fallbacks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(eject.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        eject,
        "_macos_disk_info",
        lambda _path: (
            {
                "DeviceIdentifier": "disk2s2",
                "ParentWholeDisk": "disk2",
                "MountPoint": str(tmp_path),
            },
            "",
        ),
    )
    monkeypatch.setattr(
        eject,
        "flush_filesystem",
        lambda _path, *, allow_unavailable: (True, "pending writes flushed"),
    )
    monkeypatch.setattr(eject, "_wait_for_macos_mount_gone", lambda *_args: False)

    def busy_diskutil(args: list[str], **_kwargs) -> tuple[bool, str]:
        commands.append(args)
        return False, "Volume could not be unmounted because it is in use"

    monkeypatch.setattr(eject, "_run_command", busy_diskutil)

    success, message = eject._eject_macos(tmp_path)

    assert success is False
    assert commands == [
        ["diskutil", "eject", "disk2"],
        ["diskutil", "unmount", "disk2s2"],
    ]
    assert "still mounted" in message.lower()
    assert "close" in message.lower()
    assert "retry" in message.lower()
    assert "in use" in message.lower()


def test_macos_read_only_eject_skips_write_handle_flush(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(eject.shutil, "which", lambda _command: "/usr/bin/diskutil")
    monkeypatch.setattr(
        eject,
        "_macos_disk_info",
        lambda _path: (
            {
                "DeviceIdentifier": "disk2s2",
                "ParentWholeDisk": "disk2",
                "MountPoint": str(tmp_path),
            },
            "",
        ),
    )
    monkeypatch.setattr(
        eject,
        "flush_filesystem",
        lambda *_args, **_kwargs: pytest.fail("read-only eject must not open DB rb+"),
    )
    monkeypatch.setattr(eject, "_run_command", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(eject, "_wait_for_macos_mount_gone", lambda *_args: True)

    success, _message = eject._eject_macos(tmp_path, read_only=True)

    assert success is True


def test_windows_eject_stops_before_privileged_volume_work_when_file_flush_fails(
    monkeypatch,
) -> None:
    privileged_attempts = 0
    monkeypatch.setattr(eject, "_windows_drive_is_mounted", lambda _drive: True)
    monkeypatch.setattr(
        eject,
        "flush_filesystem",
        lambda _path: (False, "FlushFileBuffers failed"),
    )

    def prepare(_drive: str) -> tuple[bool, str]:
        nonlocal privileged_attempts
        privileged_attempts += 1
        return True, "prepared"

    monkeypatch.setattr(eject, "_prepare_windows_volume_for_eject", prepare)

    success, message = eject._eject_windows(Path("E:\\"))

    assert success is False
    assert "FlushFileBuffers failed" in message
    assert privileged_attempts == 0
