from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from iopenpod.device.filesystem_profile import FilesystemProfile, VolumeIdentity
from iopenpod.device.virtual import create_virtual_ipod
from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.sync import backup_manager
from iopenpod.sync.backup_manager import (
    BackupManager,
    RestoreDurabilityPendingError,
    RestoreIncompleteError,
)


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
            "mtime_ns": time.time_ns(),
        }

    manager.snapshots_dir.mkdir(parents=True, exist_ok=True)
    total_size = sum(len(payload) for payload in files.values())
    (manager.snapshots_dir / f"{snapshot_id}.json").write_text(
        json.dumps(
            {
                "version": 2,
                "id": snapshot_id,
                "timestamp": "2026-01-01T12:00:00+00:00",
                "device_id": manager.device_id,
                "device_name": "Test iPod",
                "identity_is_stable": True,
                "file_count": len(manifest_files),
                "total_size": total_size,
                "files": manifest_files,
            }
        ),
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
        lambda _path, **_kwargs: (True, "flushed"),
        raising=False,
    )
    return profile


def test_export_snapshot_materializes_files_without_overwriting_archive(
    tmp_path: Path,
) -> None:
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "20260101_120000",
        {"iPod_Control/Music/F00/song.mp3": b"preserved bytes"},
    )
    export_parent = tmp_path / "exports"
    progress_stages: list[str] = []

    result = manager.export_snapshot(
        "20260101_120000",
        export_parent,
        progress_callback=lambda progress: progress_stages.append(progress.stage),
    )

    assert result is not None
    exported = result.destination / "iPod_Control" / "Music" / "F00" / "song.mp3"
    assert exported.read_bytes() == b"preserved bytes"
    assert result.file_count == 1
    assert result.total_size == len(b"preserved bytes")
    assert progress_stages == ["exporting", "exporting"]
    assert manager._snapshot_manifest_path("20260101_120000").is_file()


def test_export_snapshot_removes_partial_output_when_cancelled(
    tmp_path: Path,
) -> None:
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "20260101_120000",
        {
            "iPod_Control/Music/F00/one.mp3": b"one",
            "iPod_Control/Music/F00/two.mp3": b"two",
        },
    )
    export_parent = tmp_path / "exports"
    calls = 0

    def cancel_after_first_file() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    result = manager.export_snapshot(
        "20260101_120000",
        export_parent,
        is_cancelled=cancel_after_first_file,
    )

    assert result is None
    assert list(export_parent.glob("iOpenPod Export - *")) == []


def test_restore_rejects_a_different_scan_time_volume_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
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
        manager._restore_backup_from_snapshot(
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
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    extra = ipod_root / "iPod_Control" / "Music" / "F01" / "extra.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    target.write_bytes(b"old")
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"extra")
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
        lambda _path, **_kwargs: (events.append("flush") or True, "flushed"),
    )

    restored = manager._restore_backup_from_snapshot(
        snapshot.id,
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
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    target.write_bytes(b"old")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "flush_written_file",
        lambda _file: (_ for _ in ()).throw(OSError("device write failed")),
    )

    with pytest.raises(OSError, match="device write failed"):
        manager._restore_backup_from_snapshot(
            snapshot.id,
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert target.read_bytes() == b"old"
    assert list(target.parent.glob(".iop-restore-*")) == []


def test_restore_rejects_manifest_traversal_before_mutation(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"safe")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(manager, "snapshot", {"../outside.txt": b"unsafe"})

    with pytest.raises(DeviceWriteSafetyError, match="unsafe file path"):
        manager._restore_backup_from_snapshot("snapshot", ipod_root)

    assert outside.read_bytes() == b"safe"


def test_restore_rejects_corrupt_blob_before_mutation(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
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
        manager._restore_backup_from_snapshot("snapshot", ipod_root)

    assert target.read_bytes() == b"old"


def test_restore_rejects_case_collisions_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    preserved = ipod_root / "iPod_Control" / "Music" / "F01" / "preserved.mp3"
    preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"preserved")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {
            "iPod_Control/Music/F00/Song.mp3": b"first",
            "iPod_Control/Music/F00/song.mp3": b"second",
        },
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)

    with pytest.raises(DeviceWriteSafetyError, match="collide"):
        manager._restore_backup_from_snapshot(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert preserved.read_bytes() == b"preserved"


def test_restore_rejects_insufficient_peak_space_before_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    extra = ipod_root / "iPod_Control" / "Music" / "F01" / "preserved.mp3"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"preserved")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/large.mp3": b"x" * 8192},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    monkeypatch.setattr(
        backup_manager.shutil,
        "disk_usage",
        lambda _path: type("Usage", (), {"free": 0})(),
    )
    monkeypatch.setattr(
        backup_manager,
        "existing_file_allocated_size",
        lambda *_args, **_kwargs: 0,
    )

    with pytest.raises(DeviceWriteSafetyError, match="enough free space"):
        manager._restore_backup_from_snapshot(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert extra.read_bytes() == b"preserved"


def test_restore_reports_a_failed_final_filesystem_flush(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    monkeypatch.setattr(
        backup_manager,
        "flush_filesystem",
        lambda _path, **_kwargs: (False, "FlushFileBuffers failed"),
    )

    with pytest.raises(
        RestoreDurabilityPendingError,
        match="final iPod volume flush",
    ) as pending:
        manager._restore_backup_from_snapshot(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert pending.value.content_verified is True
    assert pending.value.requires_safe_eject is True
    assert target.read_bytes() == b"new"


def test_restore_reports_dirty_when_replace_mutates_then_flush_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    target = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/song.mp3": b"new"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    original_replace = backup_manager.durable_replace

    def replace_then_fail(source: str | Path, destination: str | Path) -> None:
        original_replace(source, destination)
        raise OSError("parent directory flush failed")

    monkeypatch.setattr(backup_manager, "durable_replace", replace_then_fail)

    with pytest.raises(RestoreIncompleteError, match="restore stopped after changing"):
        manager._restore_backup_from_snapshot(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert target.read_bytes() == b"new"


def test_restore_reports_dirty_when_unlink_mutates_then_flush_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    keep = ipod_root / "iPod_Control" / "Music" / "F00" / "keep.mp3"
    extra = ipod_root / "iPod_Control" / "Music" / "F01" / "extra.mp3"
    keep.parent.mkdir(parents=True)
    extra.parent.mkdir(parents=True)
    keep.write_bytes(b"keep")
    extra.write_bytes(b"remove")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/keep.mp3": b"keep"},
    )
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    original_unlink = backup_manager.durable_unlink

    def unlink_then_fail(
        path: str | Path,
        *,
        missing_ok: bool = False,
    ) -> None:
        original_unlink(path, missing_ok=missing_ok)
        if Path(path) == extra:
            raise OSError("parent directory flush failed")

    monkeypatch.setattr(backup_manager, "durable_unlink", unlink_then_fail)

    with pytest.raises(RestoreIncompleteError, match="restore stopped after changing"):
        manager._restore_backup_from_snapshot(
            "snapshot",
            ipod_root,
            expected_volume_identity_key="scan-time-volume",
        )

    assert not extra.exists()
    assert keep.read_bytes() == b"keep"


def test_real_backup_round_trip_restores_bytes_mtime_and_removes_extras(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"preserved")
    preserved_mtime = 1_700_000_000_123_456_700
    os.utime(track, ns=(preserved_mtime, preserved_mtime))

    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None

    track.write_bytes(b"changed!!")
    extra = ipod_root / "iPod_Control" / "Music" / "F01" / "extra.mp3"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"remove me")

    assert manager._restore_backup_from_snapshot(snapshot.id, ipod_root) is True
    assert track.read_bytes() == b"preserved"
    assert abs(track.stat().st_mtime_ns - preserved_mtime) <= 1_000_000
    assert not extra.exists()


def test_metadata_only_change_creates_distinct_restorable_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"same bytes")
    first_mtime = 1_700_000_000_000_000_000
    second_mtime = 1_710_000_000_000_000_000
    os.utime(track, ns=(first_mtime, first_mtime))

    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    first = manager.create_backup(ipod_root)
    assert first is not None

    os.utime(track, ns=(second_mtime, second_mtime))
    second = manager.create_backup(ipod_root)
    assert second is not None
    assert second.id != first.id

    assert manager._restore_backup_from_snapshot(first.id, ipod_root) is True
    assert abs(track.stat().st_mtime_ns - first_mtime) <= 1_000_000
    assert manager._restore_backup_from_snapshot(second.id, ipod_root) is True
    assert abs(track.stat().st_mtime_ns - second_mtime) <= 1_000_000


def test_same_size_same_mtime_content_change_is_never_hidden_by_cache(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"AAAA")
    retained_mtime = track.stat().st_mtime_ns

    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    first = manager.create_backup(ipod_root)
    assert first is not None

    track.write_bytes(b"BBBB")
    os.utime(track, ns=(retained_mtime, retained_mtime))
    second = manager.create_backup(ipod_root)

    assert second is not None
    first_manifest = manager._load_manifest(first.id)
    second_manifest = manager._load_manifest(second.id)
    assert first_manifest is not None
    assert second_manifest is not None
    relative_path = "iPod_Control/Music/F00/song.mp3"
    assert (
        first_manifest["files"][relative_path]["hash"]
        != second_manifest["files"][relative_path]["hash"]
    )


def test_backup_does_not_rehash_the_entire_source_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"AAAA")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    original_hash_file = manager._hash_file
    source_hashes = 0

    def count_source_hashes(path: Path) -> str:
        nonlocal source_hashes
        if path == track:
            source_hashes += 1
        return original_hash_file(path)

    monkeypatch.setattr(manager, "_hash_file", count_source_hashes)

    snapshot = manager.create_backup(ipod_root)

    assert snapshot is not None
    assert source_hashes == 1


def test_restore_rejects_parseable_catalog_truncation_before_mutation(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    first = ipod_root / "iPod_Control" / "Music" / "F00" / "first.mp3"
    second = ipod_root / "iPod_Control" / "Music" / "F00" / "second.mp3"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None

    manifest_path = manager._snapshot_manifest_path(snapshot.id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].pop("iPod_Control/Music/F00/second.mp3")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DeviceWriteSafetyError, match="catalog does not match"):
        manager._restore_backup_from_snapshot(snapshot.id, ipod_root)

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_manifest_checksum_tampering_is_visible_and_cannot_restore(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"safe")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None

    manifest_path = manager._snapshot_manifest_path(snapshot.id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["device_name"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    catalog = manager.list_snapshots()
    assert len(catalog) == 1
    assert catalog[0].id == snapshot.id
    assert catalog[0].is_valid is False
    assert "checksum" in catalog[0].validation_error
    with pytest.raises(DeviceWriteSafetyError, match="checksum"):
        manager._restore_backup_from_snapshot(snapshot.id, ipod_root)
    assert track.read_bytes() == b"safe"


def test_corrupt_manifest_makes_garbage_collection_fail_closed(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    manager._snapshot_manifest_path(snapshot.id).write_text(
        '{"version": 3, "files": ',
        encoding="utf-8",
    )
    orphan_hash = backup_manager.hashlib.sha256(b"orphan").hexdigest()
    orphan = manager._blob_path(orphan_hash)
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan")

    manager.garbage_collect()

    assert orphan.read_bytes() == b"orphan"


def test_invalid_snapshot_cannot_be_deleted_or_garbage_collected(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"only copy")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    manifest_path = manager._snapshot_manifest_path(snapshot.id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blob_path = manager._blob_path(
        manifest["files"]["iPod_Control/Music/F00/song.mp3"]["hash"]
    )
    manifest["file_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert manager.delete_snapshot(snapshot.id) is False

    assert manifest_path.exists()
    assert blob_path.exists()


def test_existing_corrupt_blob_is_repaired_from_fully_verified_source(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"recoverable")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    manifest = manager._load_manifest(snapshot.id)
    assert manifest is not None
    file_hash = manifest["files"]["iPod_Control/Music/F00/song.mp3"]["hash"]
    blob = manager._blob_path(file_hash)
    blob.write_bytes(b"corrupted!")

    assert manager.create_backup(ipod_root) is None
    assert blob.read_bytes() == b"recoverable"


def test_zero_file_snapshot_is_valid_and_can_clear_a_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    for path in sorted(ipod_root.rglob("*"), reverse=True):
        if path.is_file() and path.name != "iPodInfo.json":
            path.unlink()

    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    assert snapshot.file_count == 0

    added = ipod_root / "iPod_Control" / "Music" / "F00" / "later.mp3"
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_bytes(b"later")
    assert manager._restore_backup_from_snapshot(snapshot.id, ipod_root) is True
    assert not added.exists()
    assert (ipod_root / "iPodInfo.json").is_file()


def test_safety_checkpoint_and_restore_share_one_verified_device_state(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"selected snapshot")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    selected = manager.create_backup(ipod_root)
    assert selected is not None
    track.write_bytes(b"checkpoint state")

    changed_after_checkpoint = False

    def mutate_after_checkpoint(progress) -> None:
        nonlocal changed_after_checkpoint
        if progress.stage == "complete" and not changed_after_checkpoint:
            changed_after_checkpoint = True
            track.write_bytes(b"late external change")

    with pytest.raises(
        DeviceWriteSafetyError,
        match="changed after its safety checkpoint",
    ):
        manager.restore_with_safety_checkpoint(
            selected.id,
            ipod_root,
            safety_progress_callback=mutate_after_checkpoint,
        )

    assert track.read_bytes() == b"late external change"
    safety_snapshots = [
        snapshot
        for snapshot in manager.list_snapshots()
        if snapshot.reason == "pre_restore_safety"
    ]
    assert len(safety_snapshots) == 1


def test_restore_reports_initial_verification_and_lightweight_finalization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"before")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    track.write_bytes(b"after!")
    stages: list[str] = []

    assert manager._restore_backup_from_snapshot(
        snapshot.id,
        ipod_root,
        progress_callback=lambda progress: stages.append(progress.stage),
    )
    assert "verifying" in stages
    assert "committing" in stages
    assert "finalizing" in stages
    assert "final_verification" not in stages
    assert stages[-1] == "complete"


def test_successful_restore_keeps_a_forced_safety_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"selected")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    selected = manager.create_backup(ipod_root)
    assert selected is not None
    track.write_bytes(b"state before restore")

    assert manager.restore_backup(selected.id, ipod_root) is True
    assert track.read_bytes() == b"selected"

    checkpoints = [
        snapshot
        for snapshot in manager.list_snapshots()
        if snapshot.reason == "pre_restore_safety"
    ]
    assert len(checkpoints) == 1
    checkpoint_manifest = manager._load_manifest(checkpoints[0].id)
    assert checkpoint_manifest is not None
    relative_path = "iPod_Control/Music/F00/song.mp3"
    checkpoint_blob = manager._blob_path(
        checkpoint_manifest["files"][relative_path]["hash"]
    )
    assert checkpoint_blob.read_bytes() == b"state before restore"


def test_retention_never_prunes_the_snapshot_just_committed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"first")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    first = manager.create_backup(ipod_root, max_backups=0)
    assert first is not None

    first_path = manager._snapshot_manifest_path(first.id)
    manifest = json.loads(first_path.read_text(encoding="utf-8"))
    manifest["sequence"] = 999_999
    manifest["manifest_sha256"] = backup_manager._manifest_digest(manifest)
    first_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(manager, "_next_snapshot_sequence", lambda: 1)
    track.write_bytes(b"second")

    second = manager.create_backup(ipod_root, max_backups=1)

    assert second is not None
    assert manager._snapshot_manifest_path(second.id).is_file()
    assert not first_path.exists()


def test_retention_stops_when_any_manifest_is_corrupt(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"first")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    first = manager.create_backup(ipod_root, max_backups=0)
    assert first is not None
    first_path = manager._snapshot_manifest_path(first.id)
    first_manifest = json.loads(first_path.read_text(encoding="utf-8"))
    first_manifest["file_count"] += 1
    first_path.write_text(json.dumps(first_manifest), encoding="utf-8")
    track.write_bytes(b"second")

    second = manager.create_backup(ipod_root, max_backups=1)

    assert second is not None
    assert first_path.exists()
    assert manager._snapshot_manifest_path(second.id).exists()


def test_regular_retention_keeps_recent_restore_safety_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    _patch_safe_restore_environment(monkeypatch, ipod_root)
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"selected")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    selected = manager.create_backup(ipod_root, max_backups=0)
    assert selected is not None
    track.write_bytes(b"checkpoint")
    assert manager.restore_backup(selected.id, ipod_root)
    safety = next(
        snapshot
        for snapshot in manager.list_snapshots()
        if snapshot.reason == "pre_restore_safety"
    )
    track.write_bytes(b"new regular snapshot")

    newest = manager.create_backup(ipod_root, max_backups=1)

    assert newest is not None
    assert manager._snapshot_manifest_path(safety.id).exists()
    assert manager._snapshot_manifest_path(newest.id).exists()


def test_automatic_restore_checkpoints_are_bounded_and_keep_the_newest_five(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    checkpoint_ids: list[str] = []
    for index in range(7):
        track.write_bytes(f"checkpoint-{index}".encode())
        checkpoint = manager.create_backup(
            ipod_root,
            max_backups=0,
            reason="pre_restore_safety",
            _force_snapshot=True,
        )
        assert checkpoint is not None
        checkpoint_ids.append(checkpoint.id)

    manager._prune_safety_checkpoints(
        preserve_snapshot_id=checkpoint_ids[-1],
    )

    remaining = {
        snapshot.id
        for snapshot in manager.list_snapshots()
        if snapshot.reason == "pre_restore_safety"
    }
    assert remaining == set(checkpoint_ids[-5:])


def test_invalid_catalog_prevents_automatic_checkpoint_pruning(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    checkpoint_ids: list[str] = []
    for index in range(6):
        track.write_bytes(f"checkpoint-{index}".encode())
        checkpoint = manager.create_backup(
            ipod_root,
            max_backups=0,
            reason="pre_restore_safety",
            _force_snapshot=True,
        )
        assert checkpoint is not None
        checkpoint_ids.append(checkpoint.id)
    corrupt = manager.snapshots_dir / "corrupt.json"
    corrupt.write_text("not-json", encoding="utf-8")

    manager._prune_safety_checkpoints(
        preserve_snapshot_id=checkpoint_ids[-1],
    )

    assert all(
        manager._snapshot_manifest_path(snapshot_id).exists()
        for snapshot_id in checkpoint_ids
    )
    assert corrupt.exists()


def test_unresolved_identity_never_prunes_snapshots_automatically(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    track = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"first")
    manager = BackupManager(
        "unidentified_session_TEST",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=False,
    )
    first = manager.create_backup(ipod_root, max_backups=1)
    assert first is not None
    track.write_bytes(b"second")

    second = manager.create_backup(ipod_root, max_backups=1)

    assert second is not None
    assert manager._snapshot_manifest_path(first.id).exists()
    assert manager._snapshot_manifest_path(second.id).exists()


def test_committed_manifest_survives_only_temp_cleanup_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    original_publish = backup_manager.durable_publish_new

    def publish_with_cleanup_warning(source: Path, target: Path) -> bool:
        original_publish(source, target)
        return False

    monkeypatch.setattr(
        backup_manager,
        "durable_publish_new",
        publish_with_cleanup_warning,
    )
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))

    snapshot = manager.create_backup(ipod_root)

    assert snapshot is not None
    assert [item.id for item in manager.list_snapshots()] == [snapshot.id]


def test_post_publish_manifest_mismatch_is_never_reported_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    original_publish = backup_manager.durable_publish_new

    def publish_then_corrupt(source: Path, target: Path) -> bool:
        cleanup_complete = original_publish(source, target)
        target.write_text("{}", encoding="utf-8")
        return cleanup_complete

    monkeypatch.setattr(
        backup_manager,
        "durable_publish_new",
        publish_then_corrupt,
    )
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))

    with pytest.raises(
        DeviceWriteSafetyError,
        match="No snapshot was reported as complete",
    ):
        manager.create_backup(ipod_root)

    assert list(manager.snapshots_dir.glob("*.json")) == []


def test_repository_lock_rejects_concurrent_archive_writers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_ipod = tmp_path / "first-ipod"
    second_ipod = tmp_path / "second-ipod"
    create_virtual_ipod(first_ipod, "MC297")
    create_virtual_ipod(second_ipod, "MC297")
    backup_dir = tmp_path / "backups"
    first_manager = BackupManager("FIRST", backup_dir=str(backup_dir))
    second_manager = BackupManager("SECOND", backup_dir=str(backup_dir))
    writer_entered = threading.Event()
    release_writer = threading.Event()
    original_store_blob = first_manager._store_blob

    def blocking_store_blob(*args, **kwargs):
        writer_entered.set()
        assert release_writer.wait(5)
        return original_store_blob(*args, **kwargs)

    monkeypatch.setattr(first_manager, "_store_blob", blocking_store_blob)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_result = pool.submit(first_manager.create_backup, first_ipod)
        assert writer_entered.wait(5)
        with pytest.raises(
            DeviceWriteSafetyError,
            match="Another iOpenPod process is using this backup location",
        ):
            second_manager.create_backup(second_ipod)
        release_writer.set()
        assert first_result.result(timeout=10) is not None


def test_repository_lock_transitions_from_bootstrap_to_object_identity(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "new-repository"

    bootstrap_before = backup_manager._repository_bootstrap_lock_identity(
        repository
    )
    before_creation = backup_manager._repository_lock_identity(repository)
    repository.mkdir()
    bootstrap_after = backup_manager._repository_bootstrap_lock_identity(
        repository
    )
    after_creation = backup_manager._repository_lock_identity(repository)

    assert before_creation == bootstrap_before
    assert bootstrap_after == bootstrap_before
    assert after_creation != bootstrap_before
    assert (
        backup_manager._repository_lock_identity(tmp_path / "other-repository")
        != after_creation
    )


def test_repository_setup_never_writes_inside_the_ipod_before_validation(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    unsafe_parent = ipod_root / "must-not-be-created"
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(unsafe_parent / "backups"),
    )

    with pytest.raises(DeviceWriteSafetyError, match="inside the selected iPod"):
        manager.create_backup(ipod_root)

    assert not unsafe_parent.exists()


def test_repository_lock_is_not_bypassed_by_shared_manager_threads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_ipod = tmp_path / "first-ipod"
    second_ipod = tmp_path / "second-ipod"
    create_virtual_ipod(first_ipod, "MC297")
    create_virtual_ipod(second_ipod, "MC297")
    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))
    writer_entered = threading.Event()
    release_writer = threading.Event()
    original_store_blob = manager._store_blob

    def blocking_store_blob(*args, **kwargs):
        writer_entered.set()
        assert release_writer.wait(5)
        return original_store_blob(*args, **kwargs)

    monkeypatch.setattr(manager, "_store_blob", blocking_store_blob)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_result = pool.submit(manager.create_backup, first_ipod)
        assert writer_entered.wait(5)
        with pytest.raises(
            DeviceWriteSafetyError,
            match="Another iOpenPod process is using this backup location",
        ):
            manager.create_backup(second_ipod)
        release_writer.set()
        assert first_result.result(timeout=10) is not None


@pytest.mark.skipif(os.name != "nt", reason="exercises Windows path parsing")
def test_windows_rejects_posix_backslash_name_without_rewriting_it(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    preserved = ipod_root / "iPod_Control" / "Music" / "F00" / "keep.mp3"
    preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"keep")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    _write_snapshot(
        manager,
        "snapshot",
        {"iPod_Control/Music/F00/a\\b.mp3": b"unusual"},
    )

    with pytest.raises(DeviceWriteSafetyError, match="losslessly on Windows"):
        manager._restore_backup_from_snapshot("snapshot", ipod_root)

    assert preserved.read_bytes() == b"keep"
    assert not (ipod_root / "iPod_Control" / "Music" / "F00" / "a" / "b.mp3").exists()


@pytest.mark.skipif(os.name == "nt", reason="backslash is not a legal Windows filename")
def test_posix_backslash_filename_round_trips_losslessly(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    create_virtual_ipod(ipod_root, "MC297")
    unusual = ipod_root / "iPod_Control" / "Music" / "F00" / "a\\b.mp3"
    unusual.parent.mkdir(parents=True)
    unusual.write_bytes(b"unusual")
    manager = BackupManager(
        "DEVICE",
        backup_dir=str(tmp_path / "backups"),
        identity_is_stable=True,
    )
    snapshot = manager.create_backup(ipod_root)
    assert snapshot is not None
    unusual.write_bytes(b"changed")

    assert manager._restore_backup_from_snapshot(snapshot.id, ipod_root) is True
    assert unusual.read_bytes() == b"unusual"
    assert not (unusual.parent / "a" / "b.mp3").exists()
