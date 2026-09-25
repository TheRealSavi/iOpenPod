"""Native Backup Archive repository behavior and failure safety."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import iOpenPod.app.backups.repository as repository_module
from iOpenPod.app.backups import (
    ArchiveKey,
    BackupCancelledError,
    BackupDeviceIdentity,
    BackupDeviceMetadata,
    BackupError,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupProgress,
    BackupReason,
    BackupRepository,
    BackupStage,
    SnapshotIdentityState,
    SnapshotInfo,
)
from iOpenPod.app.backups.archive import (
    INCREMENTAL_SOURCE_VERIFICATION,
    catalog_digest,
)
from storage import (
    AccessMode,
    CopyResult,
    DevicePath,
    FilesystemSession,
    HostPath,
    Storage,
)
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable


def _session(tmp_path: Path) -> tuple[Path, FilesystemSession]:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, filesystem_type="fat32")
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    )
    return root, session


def _metadata() -> BackupDeviceMetadata:
    return BackupDeviceMetadata(
        family="iPod Nano",
        generation="5th Gen",
        color="Green",
        display_name="iPod Nano 5th Gen",
        product_image="iPod12-Green.png",
    )


def _identity(value: str = "SERIAL/1") -> BackupDeviceIdentity:
    return BackupDeviceIdentity(
        (
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                value,
            ),
        )
    )


def _create(
    repository: BackupRepository,
    session: FilesystemSession,
    *,
    identity: BackupDeviceIdentity | None = None,
    archive_key: ArchiveKey | None = None,
    reason: BackupReason = BackupReason.MANUAL,
    force: bool = False,
    max_backups: int = 0,
) -> SnapshotInfo | None:
    return repository.create_snapshot(
        session,
        identity=identity or _identity(),
        archive_key=archive_key,
        device_name="RoadPod",
        metadata=_metadata(),
        reason=reason,
        force=force,
        max_backups=max_backups,
    )


def _manifest_path(root: Path, archive_key: str, snapshot_id: str) -> Path:
    return root / "v4" / "archives" / archive_key / "snapshots" / f"{snapshot_id}.json"


def _object_path(root: Path, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    return root / "v4" / "objects" / "sha256" / digest[:2] / digest


def _symlink_directory(target: Path, link: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks are unavailable: {error}")


def test_create_snapshot_writes_v4_exact_paths_and_shared_objects(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    database = device / "iPod_Control" / "iTunes" / "iTunesDB"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"database")
    (device / "desktop.ini").write_bytes(b"excluded host metadata")
    (device / ".iop-abandoned.tmp").write_bytes(b"excluded Storage staging")
    root = tmp_path / "backups"
    repository = BackupRepository(root)

    snapshot = _create(repository, session)

    assert snapshot is not None
    manifest_path = _manifest_path(root, snapshot.device_id, snapshot.id)
    document = cast(
        "dict[str, object]", json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    repository_document = cast(
        "dict[str, object]",
        json.loads((root / "v4" / "repository.json").read_text(encoding="utf-8")),
    )
    files = cast("list[dict[str, object]]", document["files"])
    assert repository_document == {
        "format": "iopenpod.backup.repository",
        "version": 4,
    }
    assert document["format"] == "iopenpod.backup.snapshot"
    assert document["version"] == 4
    assert document["identity"] == _identity().to_manifest()
    assert document["source_verification"] == INCREMENTAL_SOURCE_VERIFICATION
    assert files[0]["path"] == ["iPod_Control", "iTunes", "iTunesDB"]
    assert len(files) == 1
    assert _object_path(root, b"database").read_bytes() == b"database"
    assert _create(repository, session) is None

    with repository.open_verified_snapshot(snapshot.device_id, snapshot.id) as verified:
        assert verified.identity.matches(_identity())
        assert verified.files[0].path_parts == (
            "iPod_Control",
            "iTunes",
            "iTunesDB",
        )
        assert Path(os.fspath(verified.files[0].source)).read_bytes() == b"database"


def test_capture_streams_device_content_once_and_reports_byte_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, session = _session(tmp_path)
    content = b"device content"
    (device / "file.bin").write_bytes(content)
    repository = BackupRepository(tmp_path / "backups")
    progress: list[BackupProgress] = []

    def reject_full_reread(*_args: object, **_kwargs: object) -> None:
        pytest.fail("capture performed a separate full-file fingerprint read")

    monkeypatch.setattr(session, "fingerprint", reject_full_reread)

    snapshot = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=_metadata(),
        progress=progress.append,
    )

    assert snapshot is not None
    assert any(item.stage is BackupStage.FINALIZING for item in progress)
    assert progress[-1].stage is BackupStage.COMPLETE
    assert progress[-1].completed_bytes == len(content)
    assert progress[-1].total_bytes == len(content)


def test_unchanged_capture_reuses_verified_content_without_device_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"unchanged")
    repository = BackupRepository(tmp_path / "backups")
    assert _create(repository, session) is not None

    def reject_copy(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unchanged content was copied from the device again")

    monkeypatch.setattr(session, "copy_to_host", reject_copy)

    assert _create(repository, session) is None


def test_metadata_rescan_rejects_a_tree_changed_during_single_pass_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, session = _session(tmp_path)
    first = device / "first.bin"
    second = device / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    repository = BackupRepository(tmp_path / "backups")
    copy_to_host = session.copy_to_host
    copies = 0

    def mutate_after_first_copy(
        source: DevicePath,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> CopyResult:
        nonlocal copies
        result = copy_to_host(
            source,
            destination,
            prepare_staged=prepare_staged,
            progress=progress,
        )
        copies += 1
        if copies == 1:
            second.write_bytes(b"changed size")
        return result

    monkeypatch.setattr(session, "copy_to_host", mutate_after_first_copy)

    with pytest.raises(BackupError, match=r"changed (during|while)"):
        _create(repository, session)


def test_archive_key_is_resolved_from_identity_not_mutable_display_name(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    repository = BackupRepository(tmp_path / "backups")

    snapshot = _create(repository, session)

    assert snapshot is not None
    assert repository.resolve_archive_key(_identity()).value == snapshot.device_id
    assert "RoadPod" not in snapshot.device_id
    manifest = _manifest_path(
        tmp_path / "backups", snapshot.device_id, snapshot.id
    ).read_text(encoding="utf-8")
    assert "SERIAL/1" not in manifest
    assert "source_volume_identity_key" not in manifest


def test_backup_identifier_prefers_serial_and_falls_back_to_volume() -> None:
    serial_one = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        "SERIAL-ONE",
    )
    serial_two = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        "SERIAL-TWO",
    )
    volume_one = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.VOLUME_ID,
        "volume-one",
    )
    volume_two = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.VOLUME_ID,
        "volume-two",
    )
    serial_on_first_volume = BackupDeviceIdentity((serial_one, volume_one))
    same_serial_on_second_volume = BackupDeviceIdentity((serial_one, volume_two))
    different_serial_on_first_volume = BackupDeviceIdentity((serial_two, volume_one))
    volume_only = BackupDeviceIdentity((volume_one,))

    assert serial_on_first_volume.matches(same_serial_on_second_volume)
    assert serial_on_first_volume.digest == same_serial_on_second_volume.digest
    assert not serial_on_first_volume.matches(different_serial_on_first_volume)
    assert volume_only.matches(serial_on_first_volume)
    assert volume_only.is_stable
    assert not volume_only.uses_serial_number


def test_archive_retains_serial_learned_after_volume_fallback(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"first")
    repository = BackupRepository(tmp_path / "backups")
    volume = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.VOLUME_ID,
        "volume-one",
    )
    fallback = BackupDeviceIdentity((volume,))
    first = _create(repository, session, identity=fallback)
    assert first is not None

    target.write_bytes(b"second")
    serial_one = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        "SERIAL-ONE",
    )
    identified = BackupDeviceIdentity((serial_one, volume))
    second = _create(repository, session, identity=identified)
    assert second is not None

    serial_two = BackupIdentityClaim.from_hardware(
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        "SERIAL-TWO",
    )
    conflicting = BackupDeviceIdentity((serial_two, volume))

    assert second.device_id == first.device_id
    assert repository.resolve_archive_key(conflicting).value != first.device_id


def test_explicit_archive_key_cannot_mix_backup_identifiers(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    repository = BackupRepository(tmp_path / "backups")
    key = ArchiveKey("chosen-archive")
    assert _create(repository, session, archive_key=key) is not None

    with pytest.raises(BackupError, match="identity"):
        _create(
            repository,
            session,
            identity=_identity("ANOTHER"),
            archive_key=key,
            force=True,
        )


def test_unstable_capture_requires_explicit_key_and_skips_retention(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"first")
    repository = BackupRepository(tmp_path / "backups")
    unstable = BackupDeviceIdentity()

    with pytest.raises(BackupError, match="explicit unidentified"):
        _create(repository, session, identity=unstable)

    key = ArchiveKey.for_unstable("connection-generation|volume")
    first = _create(
        repository,
        session,
        identity=unstable,
        archive_key=key,
        max_backups=1,
    )
    assert first is not None
    target.write_bytes(b"second")
    second = _create(
        repository,
        session,
        identity=unstable,
        archive_key=key,
        max_backups=1,
    )

    assert second is not None
    snapshots = repository.list_snapshots(key)
    assert len(snapshots) == 2
    assert all(
        snapshot.identity_state is SnapshotIdentityState.UNSTABLE
        for snapshot in snapshots
    )


def test_cancelled_snapshot_collects_unpublished_objects_and_stage(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    (device / "first.bin").write_bytes(b"first")
    (device / "second.bin").write_bytes(b"second")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    checks = iter((False, True))

    with pytest.raises(BackupCancelledError):
        repository.create_snapshot(
            session,
            identity=_identity(),
            device_name="RoadPod",
            metadata=_metadata(),
            cancelled=lambda: next(checks),
        )

    assert not tuple((root / "v4" / "objects" / "sha256").rglob("?" * 64))
    assert not tuple((root / "v4" / "staging").iterdir())
    assert repository.list_devices() == ()


def test_incremental_recapture_defers_deep_object_verification_until_use(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"selected")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    object_path = _object_path(root, b"selected")
    object_path.write_bytes(b"corrupt!")

    with (
        pytest.raises(BackupError, match="corrupt"),
        repository.open_verified_snapshot(snapshot.device_id, snapshot.id),
    ):
        pass

    assert _create(repository, session) is None
    assert object_path.read_bytes() == b"corrupt!"
    with (
        pytest.raises(BackupError, match="corrupt"),
        repository.open_verified_snapshot(snapshot.device_id, snapshot.id),
    ):
        pass


def test_note_update_rechecks_v4_catalog_checksum(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None

    repository.update_note(snapshot.device_id, snapshot.id, "  Before travel  ")

    assert repository.list_snapshots(snapshot.device_id)[0].note == "Before travel"
    document = cast(
        "dict[str, object]",
        json.loads(
            _manifest_path(root, snapshot.device_id, snapshot.id).read_text(
                encoding="utf-8"
            )
        ),
    )
    assert isinstance(document["catalog_sha256"], str)


def test_delete_keeps_shared_object_until_last_reference(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "shared.bin").write_bytes(b"shared")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    first = _create(repository, session)
    assert first is not None
    (device / "second.bin").write_bytes(b"second")
    second = _create(repository, session)
    assert second is not None
    shared = _object_path(root, b"shared")

    repository.delete_snapshot(first.device_id, first.id)

    assert shared.is_file()
    repository.delete_snapshot(second.device_id, second.id)
    assert not shared.exists()


def test_invalid_catalog_is_visible_and_blocks_mutation_and_collection(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    path = _manifest_path(root, snapshot.device_id, snapshot.id)
    document = cast("dict[str, object]", json.loads(path.read_text()))
    document["file_count"] = 99
    path.write_text(json.dumps(document))

    listed = repository.list_snapshots(snapshot.device_id)

    assert len(listed) == 1
    assert not listed[0].is_valid
    with pytest.raises(BackupError):
        repository.delete_snapshot(snapshot.device_id, snapshot.id)
    with pytest.raises(BackupError):
        _create(repository, session, archive_key=ArchiveKey(snapshot.device_id))
    assert path.exists()


def test_v4_catalog_requires_a_recognized_sha256_source_verification(
    tmp_path: Path,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    path = _manifest_path(root, snapshot.device_id, snapshot.id)
    document = cast("dict[str, object]", json.loads(path.read_text()))
    document["source_verification"] = "size-only"
    document["catalog_sha256"] = catalog_digest(document)
    path.write_text(json.dumps(document), encoding="utf-8")

    listed = repository.list_snapshots(snapshot.device_id)

    assert len(listed) == 1
    assert not listed[0].is_valid
    assert "source verification" in listed[0].validation_error


def test_catalog_rejects_a_file_nested_beneath_another_file(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    path = _manifest_path(root, snapshot.device_id, snapshot.id)
    document = cast("dict[str, object]", json.loads(path.read_text()))
    files = cast("list[dict[str, object]]", document["files"])
    nested = dict(files[0])
    nested["path"] = ["file.bin", "nested.bin"]
    files.append(nested)
    document["file_count"] = 2
    document["total_size"] = 8
    document["catalog_sha256"] = catalog_digest(document)
    path.write_text(json.dumps(document), encoding="utf-8")

    with (
        pytest.raises(BackupError, match="beneath another file"),
        repository.open_verified_snapshot(snapshot.device_id, snapshot.id),
    ):
        pass


def test_manifest_read_rejects_a_symlinked_archive_ancestor(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    archive = root / "v4" / "archives" / snapshot.device_id
    outside = tmp_path / "moved-archive"
    archive.rename(outside)
    _symlink_directory(outside, archive)

    with pytest.raises(BackupError, match="Unsafe Backup Archive directory"):
        repository.list_snapshots(snapshot.device_id)


def test_object_read_rejects_a_symlinked_bucket_ancestor(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    content = b"data"
    (device / "file.bin").write_bytes(content)
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    bucket = _object_path(root, content).parent
    outside = tmp_path / "moved-object-bucket"
    bucket.rename(outside)
    _symlink_directory(outside, bucket)

    with (
        pytest.raises(BackupError, match="Unsafe Backup Archive directory"),
        repository.open_verified_snapshot(snapshot.device_id, snapshot.id),
    ):
        pass


def test_export_is_verified_new_and_preserves_exact_mtime(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    target = device / "folder" / "file.bin"
    target.parent.mkdir()
    target.write_bytes(b"data")
    modified_ns = 1_700_000_000_000_000_000
    os.utime(target, ns=(modified_ns, modified_ns))
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None

    with pytest.raises(BackupError, match="outside"):
        repository.export_snapshot(snapshot.device_id, snapshot.id, root / "exports")

    result = repository.export_snapshot(
        snapshot.device_id, snapshot.id, tmp_path / "exports"
    )

    restored = result.destination / "folder" / "file.bin"
    assert restored.read_bytes() == b"data"
    assert restored.stat().st_mtime_ns == modified_ns
    second = repository.export_snapshot(
        snapshot.device_id, snapshot.id, tmp_path / "exports"
    )
    assert second.destination != result.destination


def test_v4_repository_marker_is_required_for_existing_directory(
    tmp_path: Path,
) -> None:
    native = tmp_path / "backups" / "v4"
    native.mkdir(parents=True)
    (native / "unexpected").write_bytes(b"not a repository")
    repository = BackupRepository(tmp_path / "backups")

    with pytest.raises(BackupError, match="identity marker"):
        repository.list_devices()


def test_v4_catalog_reads_are_bounded_before_json_decoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"content")
    repository = BackupRepository(tmp_path / "backups")
    snapshot = _create(repository, session)
    assert snapshot is not None
    monkeypatch.setattr(repository_module, "_MAX_CATALOG_BYTES", 32)

    with (
        pytest.raises(BackupError, match="exceeds its supported size"),
        repository.open_verified_snapshot(snapshot.device_id, snapshot.id),
    ):
        pytest.fail("An oversized v4 catalog was exposed")


def test_v4_catalog_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "file.bin").write_bytes(b"content")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    path = _manifest_path(root, snapshot.device_id, snapshot.id)
    encoded = path.read_text(encoding="utf-8")
    path.write_text(
        encoded.replace(
            '  "format": "iopenpod.backup.snapshot",',
            '  "format": "duplicate",\n  "format": "iopenpod.backup.snapshot",',
            1,
        ),
        encoding="utf-8",
    )

    listed = repository.list_snapshots(snapshot.device_id)

    assert len(listed) == 1
    assert not listed[0].is_valid
    assert "Duplicate JSON field" in listed[0].validation_error


def test_retention_flushes_catalog_removal_before_garbage_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, session = _session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"first")
    repository = BackupRepository(tmp_path / "backups")
    first = _create(repository, session)
    assert first is not None
    target.write_bytes(b"second")
    events: list[str] = []

    def record_flush(path: Path) -> None:
        events.append(f"flush:{path.name}")

    def record_garbage_collection() -> None:
        events.append("garbage-collect")

    monkeypatch.setattr(repository_module, "_flush_directory", record_flush)
    monkeypatch.setattr(repository, "_garbage_collect", record_garbage_collection)

    second = _create(repository, session, max_backups=1)

    assert second is not None
    assert events[-2:] == ["flush:snapshots", "garbage-collect"]


def test_export_rejects_case_equivalent_catalog_paths(tmp_path: Path) -> None:
    device, session = _session(tmp_path)
    (device / "File.bin").write_bytes(b"first")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    snapshot = _create(repository, session)
    assert snapshot is not None
    path = _manifest_path(root, snapshot.device_id, snapshot.id)
    document = cast("dict[str, object]", json.loads(path.read_text()))
    files = cast("list[dict[str, object]]", document["files"])
    equivalent = dict(files[0])
    equivalent["path"] = ["file.bin"]
    files.append(equivalent)
    document["file_count"] = 2
    document["total_size"] = 10
    document["catalog_sha256"] = catalog_digest(document)
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BackupError, match="case-equivalent"):
        repository.export_snapshot(
            snapshot.device_id,
            snapshot.id,
            tmp_path / "exports",
        )

    assert not (tmp_path / "exports").exists()
