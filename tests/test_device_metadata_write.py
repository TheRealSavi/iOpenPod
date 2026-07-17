from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.device import metadata_write
from iopenpod.device.filesystem_profile import FilesystemProfile, VolumeIdentity
from iopenpod.device.write_guard import DeviceWriteSafetyError


def _profile(root: Path) -> FilesystemProfile:
    return FilesystemProfile(
        mount_path=str(root),
        filesystem_type="vfat",
        reported_volume_format="FAT32",
        mount_source="/dev/sdz1",
        mount_options=("rw",),
        read_only=False,
        unsafe_write_reasons=(),
        case_sensitive=False,
        max_file_size_bytes=4 * 1024**3 - 1,
        max_component_length=255,
        allocation_unit_size=4096,
        identity=VolumeIdentity("linux", "8:33", "/dev/sdz1", "900"),
        detection_errors=(),
        inspection_path=str(root),
    )


def test_metadata_writer_flushes_then_revalidates_before_replace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = metadata_write.DeviceMetadataWriteSession(tmp_path, _profile(tmp_path))
    events: list[str] = []

    monkeypatch.setattr(
        metadata_write,
        "revalidate_device_write_readiness",
        lambda profile, **_kwargs: (events.append("revalidate") or profile),
    )
    monkeypatch.setattr(
        metadata_write,
        "flush_written_file",
        lambda _file: events.append("flush"),
    )
    original_replace = metadata_write.durable_replace

    def record_replace(source, target) -> None:
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(metadata_write, "durable_replace", record_replace)

    target = session.write_text_atomic(
        "iPod_Control/Device/SysInfo",
        "ModelNumStr: xA123\n",
        allowed_subtree="iPod_Control/Device",
    )

    assert target.read_text(encoding="utf-8") == "ModelNumStr: xA123\n"
    assert events[-3:] == ["flush", "revalidate", "replace"]


def test_metadata_session_rejects_replaced_scan_time_volume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    monkeypatch.setattr(
        metadata_write,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(metadata_write, "volume_lock_key", lambda _profile: "new-volume")

    with pytest.raises(DeviceWriteSafetyError, match="different volume"):
        with metadata_write.guarded_device_metadata_session(
            tmp_path,
            expected_volume_identity_key="old-volume",
        ):
            pytest.fail("unsafe metadata session was opened")


def test_metadata_writer_rejects_parent_traversal(tmp_path: Path) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = metadata_write.DeviceMetadataWriteSession(tmp_path, _profile(tmp_path))

    with pytest.raises(ValueError):
        session.write_bytes_atomic(
            "../outside",
            b"unsafe",
            allowed_subtree="iPod_Control/Device",
        )
