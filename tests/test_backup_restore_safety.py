from __future__ import annotations

import json
from pathlib import Path

import pytest

from iopenpod.device.filesystem_profile import FilesystemProfile, VolumeIdentity
from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.sync import backup_manager
from iopenpod.sync.backup_manager import BackupManager


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


def _write_snapshot(
    manager: BackupManager,
    snapshot_id: str,
    files: dict[str, bytes],
) -> None:
    manifest_files: dict[str, dict[str, object]] = {}
    for relative_path, payload in files.items():
        file_hash = backup_manager.hashlib.sha256(payload).hexdigest()
        blob_path = manager._blob_path(file_hash)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(payload)
        manifest_files[relative_path] = {
            "hash": file_hash,
            "size": len(payload),
            "mtime_ns": 0,
        }

    manager.snapshots_dir.mkdir(parents=True, exist_ok=True)
    (manager.snapshots_dir / f"{snapshot_id}.json").write_text(
        json.dumps({"id": snapshot_id, "files": manifest_files}),
        encoding="utf-8",
    )


def _patch_safe_restore_environment(
    monkeypatch: pytest.MonkeyPatch,
    ipod_root: Path,
) -> FilesystemProfile:
    profile = _profile(ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        backup_manager,
        "revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
        raising=False,
    )
    monkeypatch.setattr(
        backup_manager,
        "volume_lock_key",
        lambda _profile: "scan-time-volume",
    )
    monkeypatch.setattr(
        backup_manager,
        "flush_filesystem",
        lambda _path: (True, "flushed"),
        raising=False,
    )
    return profile


def test_restore_rejects_a_different_scan_time_volume_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    profile = _profile(ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
        raising=False,
    )
    monkeypatch.setattr(
        backup_manager,
        "volume_lock_key",
        lambda _profile: "currently-mounted-volume",
        raising=False,
    )

    with pytest.raises(DeviceWriteSafetyError, match="different volume"):
        manager.restore_backup(
            "snapshot",
            ipod_root,
            reported_volume_format="FAT32",
            expected_volume_identity_key="scan-time-volume",
        )

    assert target.read_bytes() == b"old"


def test_restore_uses_durable_temp_replacement_and_flushes_the_volume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    extra = ipod_root / "iPod_Control" / "Music" / "F01" / "extra.mp3"
    target.parent.mkdir(parents=True)
    extra.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    extra.write_bytes(b"extra")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    events: list[str] = []
    original_replace = backup_manager.durable_replace
    original_unlink = backup_manager.durable_unlink

    def record_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        assert source_path.parent == Path(destination).parent
        assert source_path.name.startswith(".iop-restore-")
        assert source_path.read_bytes() == b"new"
        events.append("replace")
        original_replace(source, destination)

    def record_unlink(path: str | Path, *, missing_ok: bool = False) -> None:
        events.append("unlink")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(backup_manager, "durable_replace", record_replace, raising=False)
    monkeypatch.setattr(backup_manager, "durable_unlink", record_unlink, raising=False)
    monkeypatch.setattr(
        backup_manager,
        "flush_filesystem",
        lambda _path: (events.append("flush") or True, "flushed"),
    )

    restored = manager.restore_backup(
        "snapshot",
        ipod_root,
        reported_volume_format="FAT32",
        expected_volume_identity_key="scan-time-volume",
    )

    assert restored is True
    assert target.read_bytes() == b"new"
    assert not extra.exists()
    assert events == ["unlink", "replace", "flush"]
    assert list(target.parent.glob(".iop-restore-*")) == []


def test_restore_keeps_the_old_file_when_temp_copy_flush_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "flush_written_file",
        lambda _file: (_ for _ in ()).throw(OSError("device write failed")),
    )

    with pytest.raises(OSError, match="device write failed"):
        manager.restore_backup(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert target.read_bytes() == b"old"
    assert list(target.parent.glob(".iop-restore-*")) == []


def test_restore_rejects_manifest_traversal_before_mutation(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"safe")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(manager, "snapshot", {"../outside.txt": b"unsafe"})

    with pytest.raises(DeviceWriteSafetyError, match="unsafe file path"):
        manager.restore_backup("snapshot", ipod_root)

    assert outside.read_bytes() == b"safe"


def test_restore_rejects_corrupt_blob_before_mutation(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    manifest = manager._load_manifest("snapshot")
    assert manifest is not None
    blob_hash = manifest["files"]["iPod_Control/Music/F00/song.mp3"]["hash"]
    manager._blob_path(blob_hash).write_bytes(b"bad")

    with pytest.raises(DeviceWriteSafetyError, match="SHA-256"):
        manager.restore_backup("snapshot", ipod_root)

    assert target.read_bytes() == b"old"


def test_restore_reports_a_failed_final_filesystem_flush(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "flush_filesystem",
        lambda _path: (False, "FlushFileBuffers failed"),
    )

    with pytest.raises(DeviceWriteSafetyError, match="could not be flushed safely"):
        manager.restore_backup(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert target.read_bytes() == b"new"
