from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.device import write_readiness
from iopenpod.device.filesystem_profile import (
    FilesystemProfile,
    FilesystemRevalidation,
    VolumeIdentity,
)
from iopenpod.device.write_guard import DeviceWriteSafetyError


def _profile(tmp_path: Path, **changes) -> FilesystemProfile:
    (tmp_path / "iPod_Control").mkdir(exist_ok=True)
    values = {
        "mount_path": str(tmp_path),
        "filesystem_type": "vfat",
        "reported_volume_format": "FAT32",
        "mount_source": "/dev/sdb1",
        "mount_options": ("rw",),
        "read_only": False,
        "unsafe_write_reasons": (),
        "case_sensitive": False,
        "max_file_size_bytes": 4 * 1024**3 - 1,
        "max_component_length": 255,
        "allocation_unit_size": 4096,
        "identity": VolumeIdentity("linux", "8:17", "/dev/sdb1", "317"),
        "detection_errors": (),
    }
    values.update(changes)
    return FilesystemProfile(**values)


def test_inspect_write_readiness_returns_a_safe_profile(monkeypatch, tmp_path: Path) -> None:
    expected = _profile(tmp_path)
    monkeypatch.setattr(
        write_readiness,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: expected,
    )

    profile = write_readiness.inspect_device_write_readiness(
        tmp_path,
        reported_volume_format="FAT32",
    )

    assert profile is expected


def test_inspect_write_readiness_fails_closed_for_unsafe_mount(
    monkeypatch,
    tmp_path: Path,
) -> None:
    unsafe = _profile(
        tmp_path,
        unsafe_write_reasons=("Linux HFS force mount is unsafe",),
    )
    monkeypatch.setattr(
        write_readiness,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: unsafe,
    )

    with pytest.raises(DeviceWriteSafetyError, match="force mount"):
        write_readiness.inspect_device_write_readiness(tmp_path)


def test_revalidation_fails_before_writing_to_a_changed_volume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    retained = _profile(tmp_path)
    changed = _profile(
        tmp_path,
        identity=VolumeIdentity("linux", "8:18", "/dev/sdc1", "318"),
    )
    monkeypatch.setattr(
        write_readiness,
        "revalidate_filesystem_profile",
        lambda _profile, **_kwargs: FilesystemRevalidation(
            False,
            "volume_changed",
            "A different volume is mounted at the inspected path.",
            changed,
        ),
    )

    with pytest.raises(DeviceWriteSafetyError, match="different volume"):
        write_readiness.revalidate_device_write_readiness(retained)


def test_volume_lock_key_contains_stable_identity_not_mount_label(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    assert write_readiness.volume_lock_key(profile) == (
        "linux|8:17|/dev/sdb1|317"
    )


def test_physical_ipod_path_must_be_the_observed_mount_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    selected = tmp_path / "media" / "IPOD"
    selected.mkdir(parents=True)
    containing_volume = _profile(tmp_path, mount_path=str(tmp_path))
    monkeypatch.setattr(
        write_readiness,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: containing_volume,
    )

    with pytest.raises(DeviceWriteSafetyError, match="not mounted"):
        write_readiness.inspect_device_write_readiness(selected)


def test_physical_ipod_rejects_non_ipod_filesystem(
    monkeypatch,
    tmp_path: Path,
) -> None:
    unsupported = _profile(tmp_path, filesystem_type="ntfs")
    monkeypatch.setattr(
        write_readiness,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: unsupported,
    )

    with pytest.raises(DeviceWriteSafetyError, match="unsupported filesystem"):
        write_readiness.inspect_device_write_readiness(tmp_path)


def test_virtual_ipod_directory_may_live_below_a_host_mount(
    monkeypatch,
    tmp_path: Path,
) -> None:
    selected = tmp_path / "virtual-ipod"
    selected.mkdir()
    (selected / "iPodInfo.json").write_text("{}", encoding="utf-8")
    containing_volume = _profile(tmp_path, mount_path=str(tmp_path))
    monkeypatch.setattr(
        write_readiness,
        "inspect_filesystem_profile",
        lambda *_args, **_kwargs: containing_volume,
    )

    assert write_readiness.inspect_device_write_readiness(selected) is containing_volume
