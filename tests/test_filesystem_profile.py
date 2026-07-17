from __future__ import annotations

import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

from iopenpod.device import filesystem_profile


def _linux_mountinfo_line(
    mount_path: Path,
    *,
    mount_id: int = 317,
    device: str = "8:17",
    filesystem: str = "vfat",
    source: str = "/dev/sdb1",
    options: str = "rw,nosuid,nodev,relatime",
    super_options: str = "rw,fmask=0022,dmask=0022",
) -> str:
    encoded_mount = str(mount_path).replace(" ", r"\040")
    return (
        f"{mount_id} 29 {device} / {encoded_mount} {options} - "
        f"{filesystem} {source} {super_options}\n"
    )


def test_linux_profile_reports_mounted_filesystem_limits_and_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(_linux_mountinfo_line(tmp_path), encoding="utf-8")
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )

    profile = filesystem_profile.inspect_filesystem_profile(
        tmp_path,
        reported_volume_format="FAT32",
    )

    assert profile.mount_path == os.path.realpath(tmp_path)
    assert profile.filesystem_type == "vfat"
    assert profile.reported_volume_format == "FAT32"
    assert profile.mount_source == "/dev/sdb1"
    assert profile.mount_options == (
        "rw",
        "nosuid",
        "nodev",
        "relatime",
        "fmask=0022",
        "dmask=0022",
    )
    assert profile.read_only is False
    assert profile.safe_for_writes is True
    assert profile.case_sensitive is None
    assert profile.max_file_size_bytes == 4 * 1024**3 - 1
    assert profile.max_component_length is not None
    assert profile.max_component_length > 0
    assert profile.allocation_unit_size is not None
    assert profile.allocation_unit_size > 0
    assert profile.identity == filesystem_profile.VolumeIdentity(
        operating_system="linux",
        device_id="8:17",
        volume_id="/dev/sdb1",
        mount_instance="317",
    )
    assert profile.detection_errors == ()


def test_revalidation_stops_when_linux_mount_instance_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(_linux_mountinfo_line(tmp_path), encoding="utf-8")
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )
    original = filesystem_profile.inspect_filesystem_profile(tmp_path)
    mountinfo.write_text(
        _linux_mountinfo_line(tmp_path, mount_id=318),
        encoding="utf-8",
    )

    result = filesystem_profile.revalidate_filesystem_profile(original)

    assert result.safe_to_continue is False
    assert result.current_identity.mount_instance == "318"
    assert "mount instance changed" in result.reason.casefold()


def test_requested_case_probe_observes_behavior_and_removes_probe_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    reference = tmp_path / "ReferenceMiXeD"
    reference.write_bytes(b"")
    expected_case_sensitive = not (tmp_path / "referencemixed").exists()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(_linux_mountinfo_line(tmp_path), encoding="utf-8")
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )

    profile = filesystem_profile.inspect_filesystem_profile(
        tmp_path,
        probe_case_sensitivity=True,
    )

    assert profile.case_sensitive is expected_case_sensitive
    assert not any(
        child.name.startswith(".iOpenPod_CaseProbe_")
        for child in tmp_path.iterdir()
    )

    probes: list[str] = []
    monkeypatch.setattr(
        filesystem_profile,
        "_probe_case_sensitivity",
        lambda path: (probes.append(path) or expected_case_sensitive, ""),
    )
    revalidated = filesystem_profile.revalidate_filesystem_profile(profile)

    assert revalidated.safe_to_continue
    assert revalidated.current_profile.case_sensitive is expected_case_sensitive
    assert probes == []


def test_case_probe_cleanup_failure_is_reported_as_unsafe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        filesystem_profile.Path,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("device I/O error")),
    )

    case_sensitive, error = filesystem_profile._probe_case_sensitivity(
        str(tmp_path)
    )

    assert case_sensitive is None
    assert "Could not remove filesystem case probe" in error


def test_case_probe_uses_requested_ipod_database_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mount_root = tmp_path / "mount"
    requested_ipod = mount_root / "virtual-ipod"
    database_directory = requested_ipod / "iPod_Control" / "iTunes"
    database_directory.mkdir(parents=True)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(_linux_mountinfo_line(mount_root), encoding="utf-8")
    probed: list[str] = []
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(
        filesystem_profile.os,
        "pathconf",
        lambda *_args: 255,
        raising=False,
    )
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )
    monkeypatch.setattr(
        filesystem_profile,
        "_probe_case_sensitivity",
        lambda path: (probed.append(path) or False, ""),
    )

    profile = filesystem_profile.inspect_filesystem_profile(
        requested_ipod,
        probe_case_sensitivity=True,
    )

    assert probed == [str(database_directory)]
    assert profile.inspection_path == os.path.realpath(requested_ipod)
    assert profile.mount_path == os.path.realpath(mount_root)


def test_macos_profile_uses_diskutil_volume_identity_and_format(
    monkeypatch,
    tmp_path: Path,
) -> None:
    disk_info = {
        "DeviceIdentifier": "disk4s2",
        "VolumeUUID": "90C5CF3C-6734-4C25-867B-AF4EE52911CC",
        "FilesystemType": "hfs",
        "MountPoint": str(tmp_path),
        "Writable": True,
        "AllocationBlockSize": 4096,
        "MountOptions": ["local", "nodev", "nosuid"],
    }
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout=plistlib.dumps(disk_info), stderr=b"")

    monkeypatch.setattr(filesystem_profile.sys, "platform", "darwin")
    monkeypatch.setattr(filesystem_profile.subprocess, "run", fake_run)
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)

    profile = filesystem_profile.inspect_filesystem_profile(
        tmp_path,
        reported_volume_format="HFS+",
    )

    assert commands == [["diskutil", "info", "-plist", os.path.realpath(tmp_path)]]
    assert profile.filesystem_type == "hfs"
    assert profile.reported_volume_format == "HFS+"
    assert profile.mount_source == "/dev/disk4s2"
    assert profile.mount_options == ("local", "nodev", "nosuid")
    assert profile.read_only is False
    assert profile.allocation_unit_size == 4096
    assert profile.identity == filesystem_profile.VolumeIdentity(
        operating_system="macos",
        device_id="disk4s2",
        volume_id="90C5CF3C-6734-4C25-867B-AF4EE52911CC",
        mount_instance="disk4s2",
    )
    assert profile.safe_for_writes is True


def test_windows_profile_uses_volume_guid_serial_and_geometry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeKernel32:
        @staticmethod
        def GetVolumeInformationW(
            _root,
            _volume_name,
            _volume_name_size,
            serial,
            max_component,
            flags,
            filesystem_name,
            _filesystem_name_size,
        ):
            serial._obj.value = 0x91ABCDEF
            max_component._obj.value = 255
            flags._obj.value = 0x00000003
            filesystem_name.value = "NTFS"
            return 1

        @staticmethod
        def GetVolumeNameForVolumeMountPointW(_root, volume_name, _size):
            volume_name.value = "\\\\?\\Volume{E51E9670-112A-48A7-A944-06C06EF26C77}\\"
            return 1

        @staticmethod
        def GetDiskFreeSpaceW(
            _root,
            sectors_per_cluster,
            bytes_per_sector,
            free_clusters,
            total_clusters,
        ):
            sectors_per_cluster._obj.value = 8
            bytes_per_sector._obj.value = 512
            free_clusters._obj.value = 100
            total_clusters._obj.value = 200
            return 1

    monkeypatch.setattr(filesystem_profile.sys, "platform", "win32")
    monkeypatch.setattr(
        filesystem_profile.ctypes,
        "windll",
        SimpleNamespace(kernel32=FakeKernel32()),
        raising=False,
    )

    profile = filesystem_profile.inspect_filesystem_profile(tmp_path)

    assert profile.filesystem_type == "ntfs"
    assert profile.mount_source == "\\\\?\\Volume{E51E9670-112A-48A7-A944-06C06EF26C77}\\"
    assert profile.mount_options == ()
    assert profile.read_only is False
    assert profile.max_component_length == 255
    assert profile.allocation_unit_size == 4096
    assert profile.identity == filesystem_profile.VolumeIdentity(
        operating_system="windows",
        device_id="\\\\?\\Volume{E51E9670-112A-48A7-A944-06C06EF26C77}\\",
        volume_id="91ABCDEF",
        mount_instance="\\\\?\\Volume{E51E9670-112A-48A7-A944-06C06EF26C77}\\",
    )
    assert profile.safe_for_writes is True


def test_linux_hfs_force_mount_is_never_safe_for_writes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        _linux_mountinfo_line(
            tmp_path,
            filesystem="hfsplus",
            options="rw,nosuid,nodev,force",
            super_options="rw,force",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )

    profile = filesystem_profile.inspect_filesystem_profile(tmp_path)

    assert profile.safe_for_writes is False
    assert profile.unsafe_write_reasons == (
        "Linux HFS volume is mounted with the unsafe 'force' option",
    )


def test_unsafe_hfs_mount_is_rejected_without_case_probe_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        _linux_mountinfo_line(
            tmp_path,
            filesystem="hfsplus",
            options="rw,nosuid,nodev,force",
            super_options="rw,force",
        ),
        encoding="utf-8",
    )
    probes: list[str] = []
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(filesystem_profile, "_LINUX_MOUNTINFO", mountinfo)
    monkeypatch.setattr(
        filesystem_profile,
        "_probe_case_sensitivity",
        lambda path: (probes.append(path) or False, ""),
    )

    profile = filesystem_profile.inspect_filesystem_profile(
        tmp_path,
        probe_case_sensitivity=True,
    )

    assert profile.safe_for_writes is False
    assert probes == []


def test_profile_fails_closed_when_mount_identity_cannot_be_detected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(filesystem_profile.sys, "platform", "linux")
    monkeypatch.setattr(
        filesystem_profile,
        "_LINUX_MOUNTINFO",
        tmp_path / "does-not-exist",
    )
    monkeypatch.setattr(filesystem_profile.os, "pathconf", lambda *_args: 255, raising=False)
    monkeypatch.setattr(
        filesystem_profile.os,
        "statvfs",
        lambda *_args: type("Stats", (), {"f_frsize": 4096, "f_bsize": 4096})(),
        raising=False,
    )

    profile = filesystem_profile.inspect_filesystem_profile(tmp_path)

    assert profile.safe_for_writes is False
    assert profile.identity.is_complete is False
    assert any("mount table" in error.casefold() for error in profile.detection_errors)
