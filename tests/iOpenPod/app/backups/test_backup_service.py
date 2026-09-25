"""Backup application workflows across the repository and Storage seams."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from iOpenPod.app.backups import (
    ArchiveKey,
    BackupDeviceContext,
    BackupDeviceIdentity,
    BackupDeviceMetadata,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupReason,
    BackupRecoveryRequiredError,
    BackupRepository,
    BackupService,
    LegacyIdentityClaim,
    RestoreRecoveryOutcome,
    SnapshotIdentityState,
)
from iOpenPod.app.backups.outcomes import (
    BackupFailureCode,
    CaptureCreated,
    CaptureUnchanged,
    ExportFailed,
    ImportCompleted,
    ImportFailed,
    RestoreCompleted,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.app.backups.service import backup_failure_for
from storage import (
    AccessMode,
    DevicePath,
    FilesystemSession,
    Storage,
    StorageCapacityError,
)
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    import pytest

    from iOpenPod.app.models.device import ActiveIPod


def _identity(value: str = "SERIAL-ONE") -> BackupDeviceIdentity:
    return BackupDeviceIdentity(
        (
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                value,
            ),
        )
    )


def _context(
    identity: BackupDeviceIdentity | None = None,
    *,
    legacy_identity_keys: tuple[str, ...] = (),
) -> BackupDeviceContext:
    resolved = identity or _identity()
    return BackupDeviceContext(
        archive_key=None if resolved.is_stable else ArchiveKey.for_unstable("session"),
        display_name="RoadPod",
        identity=resolved,
        filesystem_type="fat32",
        metadata=BackupDeviceMetadata(
            family="iPod Classic",
            generation="6th Gen",
            display_name="iPod Classic 6th Gen",
        ),
        legacy_identity_claims=tuple(
            LegacyIdentityClaim.from_original_key(value)
            for value in legacy_identity_keys
        ),
    )


class _Devices:
    def __init__(
        self,
        context: BackupDeviceContext,
        session: FilesystemSession,
    ) -> None:
        self.context = context
        self.session = session
        self.accesses: list[AccessMode] = []
        self.host_path_checks: list[tuple[Path, ...]] = []

    def backup_device_context(self) -> BackupDeviceContext:
        return self.context

    def require_backup_host_paths(self, *paths: Path) -> None:
        self.host_path_checks.append(paths)

    @contextmanager
    def backup_session(
        self,
        _expected: ActiveIPod,
        _backup_root: Path,
        *,
        access: AccessMode,
    ) -> Generator[tuple[BackupDeviceContext, FilesystemSession]]:
        self.accesses.append(access)
        yield self.context, self.session


def _device_session(
    tmp_path: Path,
) -> tuple[Path, VirtualStoragePlatform, FilesystemSession]:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, filesystem_type="fat32")
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    )
    return root, platform, session


def _active() -> ActiveIPod:
    return cast("ActiveIPod", object())


def _write_original_v3(root: Path) -> tuple[str, bytes]:
    device_id = "SERIAL-ONE"
    snapshot_id = "legacy-snapshot"
    content = b"legacy database"
    digest = hashlib.sha256(content).hexdigest()
    blob = root / "blobs" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)
    document: dict[str, object] = {
        "version": 3,
        "id": snapshot_id,
        "timestamp": "2026-02-28T15:14:00+00:00",
        "device_id": device_id,
        "device_name": "LegacyPod",
        "device_meta": {"model_family": "iPod Classic"},
        "identity_is_stable": True,
        "reason": "manual",
        "note": "",
        "file_count": 1,
        "total_size": len(content),
        "files": {
            "iPod_Control/iTunes/iTunesDB": {
                "hash": digest,
                "size": len(content),
                "mtime_ns": 1_700_000_000_000_000_000,
            }
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    document["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    manifest = root / device_id / "snapshots" / f"{snapshot_id}.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return device_id, content


def test_capture_returns_created_then_unchanged_outcomes(tmp_path: Path) -> None:
    device, _platform, session = _device_session(tmp_path)
    (device / "file.bin").write_bytes(b"device state")
    devices = _Devices(_context(), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    root = tmp_path / "backups"

    first = service.create_snapshot(root, _active(), max_backups=3)
    second = service.create_snapshot(root, _active(), max_backups=3)

    assert isinstance(first, CaptureCreated)
    assert isinstance(second, CaptureUnchanged)
    assert second.snapshot_id == first.snapshot.id
    assert devices.accesses == [AccessMode.READ_ONLY, AccessMode.READ_ONLY]
    assert BackupRepository(root).list_snapshots(first.snapshot.device_id) == (
        first.snapshot,
    )


def test_empty_connected_catalog_uses_active_ipod_name_and_metadata(
    tmp_path: Path,
) -> None:
    _device, _platform, session = _device_session(tmp_path)
    context = _context()
    service = BackupService(
        cast("object", _Devices(context, session))  # type: ignore[arg-type]
    )
    root = tmp_path / "backups"
    inventory = service.inventory(root)

    catalog = service.catalog(root, inventory.connected_device_id)

    assert catalog.snapshots == ()
    assert catalog.device.device_name == context.display_name
    assert catalog.device.metadata == context.metadata
    assert catalog.device.has_backup_identifier
    assert catalog.device.connected
    assert catalog.device.identity_state is SnapshotIdentityState.NATIVE


def test_restore_replaces_and_removes_as_one_verified_bounded_transaction(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    database = device / "iPod_Control" / "iTunes" / "iTunesDB"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"selected state")
    os.utime(
        database,
        ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000),
    )
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    selected = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=_context().metadata,
    )
    assert selected is not None
    database.write_bytes(b"current state")
    (device / "extra.bin").write_bytes(b"remove me")
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )

    outcome = service.restore_snapshot(
        root,
        _active(),
        device_id=selected.device_id,
        snapshot_id=selected.id,
    )

    assert isinstance(outcome, RestoreCompleted)
    assert outcome.snapshot_id == selected.id
    assert outcome.flush.complete
    assert database.read_bytes() == b"selected state"
    assert session.modified_time_matches(
        database.stat().st_mtime_ns,
        1_700_000_000_000_000_000,
    )
    assert not (device / "extra.bin").exists()
    assert not tuple((device / ".iopenpod-recovery").glob("*"))
    assert repository.list_restore_recoveries() == ()
    safety = next(
        snapshot
        for snapshot in repository.list_snapshots(selected.device_id)
        if snapshot.id == outcome.safety_snapshot_id
    )
    assert safety.reason is BackupReason.PRE_RESTORE_SAFETY


def test_restore_of_identical_content_is_a_verified_no_write_outcome(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"already selected")
    devices = _Devices(_context(), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    root = tmp_path / "backups"
    captured = service.create_snapshot(root, _active(), max_backups=0)
    assert isinstance(captured, CaptureCreated)

    outcome = service.restore_snapshot(
        root,
        _active(),
        device_id=captured.snapshot.device_id,
        snapshot_id=captured.snapshot.id,
    )

    assert isinstance(outcome, RestoreUnchanged)
    assert target.read_bytes() == b"already selected"
    assert BackupRepository(root).list_restore_recoveries() == ()
    assert devices.accesses == [AccessMode.READ_ONLY, AccessMode.READ_WRITE]


def test_restore_preflight_failure_clears_unpublished_recovery_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"selected")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    selected = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=_context().metadata,
    )
    assert selected is not None
    target.write_bytes(b"current")
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )

    def fail_preflight(*_args: object, **_kwargs: object) -> object:
        raise StorageCapacityError("not enough recovery capacity")

    monkeypatch.setattr(FilesystemSession, "execute_transaction", fail_preflight)

    outcome = service.restore_snapshot(
        root,
        _active(),
        device_id=selected.device_id,
        snapshot_id=selected.id,
    )

    assert isinstance(outcome, RestorePreMutationFailure)
    assert outcome.failure.code is BackupFailureCode.INSUFFICIENT_SPACE
    assert outcome.safety_snapshot_id is not None
    assert target.read_bytes() == b"current"
    assert repository.list_restore_recoveries() == ()
    assert not (device / ".iopenpod-recovery").exists()


def test_backup_identifier_mismatch_fails_before_safety_capture_or_device_change(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"selected")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    selected = repository.create_snapshot(
        session,
        identity=_identity("OTHER-IPOD"),
        device_name="OtherPod",
        metadata=BackupDeviceMetadata(),
    )
    assert selected is not None
    target.write_bytes(b"current")
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )

    outcome = service.restore_snapshot(
        root,
        _active(),
        device_id=selected.device_id,
        snapshot_id=selected.id,
    )

    assert isinstance(outcome, RestorePreMutationFailure)
    assert outcome.failure.code is BackupFailureCode.DEVICE_IDENTITY_MISMATCH
    assert outcome.safety_snapshot_id is None
    assert target.read_bytes() == b"current"
    assert len(repository.list_snapshots(selected.device_id)) == 1


def test_original_import_requires_matching_identity_and_per_restore_confirmation(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    current = device / "current.bin"
    current.write_bytes(b"current")
    source = tmp_path / "original"
    source.mkdir()
    legacy_id, legacy_content = _write_original_v3(source)
    root = tmp_path / "backups"
    devices = _Devices(_context(legacy_identity_keys=(legacy_id,)), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]

    imported = BackupRepository(root).import_original(source)

    assert len(imported.imported) == 1
    repository = BackupRepository(root)
    imported_device = repository.list_devices()[0]
    selected = repository.list_snapshots(imported_device.device_id)[0]
    assert selected.identity_state is SnapshotIdentityState.LEGACY_ASSERTED

    unconfirmed = service.restore_snapshot(
        root,
        _active(),
        device_id=selected.device_id,
        snapshot_id=selected.id,
    )

    assert isinstance(unconfirmed, RestorePreMutationFailure)
    assert unconfirmed.failure.code is BackupFailureCode.DEVICE_IDENTITY_MISMATCH
    assert current.read_bytes() == b"current"

    confirmed = service.restore_snapshot(
        root,
        _active(),
        device_id=selected.device_id,
        snapshot_id=selected.id,
        legacy_confirmed=True,
    )

    assert isinstance(confirmed, RestoreCompleted)
    restored = device / "iPod_Control" / "iTunes" / "iTunesDB"
    assert restored.read_bytes() == legacy_content
    assert not current.exists()


def test_original_import_with_connected_serial_joins_the_native_archive(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    (device / "current.bin").write_bytes(b"current")
    source = tmp_path / "original"
    source.mkdir()
    legacy_id, _legacy_content = _write_original_v3(source)
    root = tmp_path / "backups"
    devices = _Devices(_context(legacy_identity_keys=(legacy_id,)), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    captured = service.create_snapshot(root, _active(), max_backups=3)
    assert isinstance(captured, CaptureCreated)

    imported = service.import_original(root, source)
    inventory = service.inventory(root)

    assert isinstance(imported, ImportCompleted)
    assert inventory.connected_device_id == captured.snapshot.device_id
    assert len(inventory.devices) == 1
    assert inventory.devices[0].device_id == captured.snapshot.device_id
    assert inventory.devices[0].snapshot_count == 2
    catalog = service.catalog(root, captured.snapshot.device_id)
    assert len(catalog.snapshots) == 2
    assert all(
        snapshot.identity_state is SnapshotIdentityState.NATIVE
        for snapshot in catalog.snapshots
    )


def test_reimport_with_connected_serial_repairs_a_split_legacy_archive(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    (device / "current.bin").write_bytes(b"current")
    source = tmp_path / "original"
    source.mkdir()
    legacy_id, _legacy_content = _write_original_v3(source)
    root = tmp_path / "backups"
    devices = _Devices(_context(legacy_identity_keys=(legacy_id,)), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    captured = service.create_snapshot(root, _active(), max_backups=3)
    assert isinstance(captured, CaptureCreated)
    repository = BackupRepository(root)
    first_import = repository.import_original(source)
    assert len(first_import.imported) == 1
    assert len(repository.list_devices()) == 2

    repeated = service.import_original(root, source)
    inventory = service.inventory(root)

    assert isinstance(repeated, ImportCompleted)
    assert repeated.already_present.snapshots == 1
    assert len(inventory.devices) == 1
    assert inventory.devices[0].device_id == captured.snapshot.device_id
    assert inventory.devices[0].snapshot_count == 2
    assert all(
        snapshot.identity_state is SnapshotIdentityState.NATIVE
        for snapshot in repository.list_snapshots(captured.snapshot.device_id)
    )


def test_import_overlap_returns_an_actionable_unsafe_destination(
    tmp_path: Path,
) -> None:
    _device, _platform, session = _device_session(tmp_path)
    root = tmp_path / "backups"
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )

    outcome = service.import_original(root, root / "original")

    assert isinstance(outcome, ImportFailed)
    assert outcome.failure.code is BackupFailureCode.UNSAFE_DESTINATION
    assert "separate folders" in outcome.failure.action


def test_export_overlap_returns_an_actionable_unsafe_destination(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    (device / "file.bin").write_bytes(b"data")
    devices = _Devices(_context(), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    root = tmp_path / "backups"
    captured = service.create_snapshot(root, _active(), max_backups=0)
    assert isinstance(captured, CaptureCreated)

    outcome = service.export_snapshot(
        root,
        captured.snapshot.device_id,
        captured.snapshot.id,
        root / "exports",
    )

    assert isinstance(outcome, ExportFailed)
    assert outcome.failure.code is BackupFailureCode.UNSAFE_DESTINATION
    assert devices.host_path_checks == [(root, root / "exports")]


def test_resolved_recovery_records_do_not_survive_verified_restore(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    (device / "file.bin").write_bytes(b"first")
    root = tmp_path / "backups"
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )
    captured = service.create_snapshot(root, _active(), max_backups=0)
    assert isinstance(captured, CaptureCreated)
    (device / "file.bin").write_bytes(b"second")

    restored = service.restore_snapshot(
        root,
        _active(),
        device_id=captured.snapshot.device_id,
        snapshot_id=captured.snapshot.id,
    )

    assert isinstance(restored, RestoreCompleted)
    assert BackupRepository(root).list_restore_recoveries() == ()
    # The Host record is cleared only after the exact terminal state was verified.
    assert RestoreRecoveryOutcome.VERIFIED_COMPLETION.value == "verified_completion"


def test_interrupted_restore_is_discoverable_and_rolls_back_from_safety_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"selected")
    root = tmp_path / "backups"
    devices = _Devices(_context(), session)
    service = BackupService(cast("object", devices))  # type: ignore[arg-type]
    captured = service.create_snapshot(root, _active(), max_backups=0)
    assert isinstance(captured, CaptureCreated)
    target.write_bytes(b"current before restore")
    native_move = FilesystemSession._move_file  # pyright: ignore[reportPrivateUsage]
    interrupted = False

    def move_then_interrupt(
        current_session: FilesystemSession,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal interrupted
        result = native_move(current_session, *args, **kwargs)  # type: ignore[arg-type]
        if not interrupted:
            interrupted = True
            raise OSError("simulated disconnect after publication")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(FilesystemSession, "_move_file", move_then_interrupt)
        incomplete = service.restore_snapshot(
            root,
            _active(),
            device_id=captured.snapshot.device_id,
            snapshot_id=captured.snapshot.id,
        )

    assert incomplete.kind == "restore.incomplete"
    inventory = service.inventory(root)
    assert len(inventory.pending_recoveries) == 1
    record = inventory.pending_recoveries[0]

    recovered = service.recover_restore(root, _active(), recovery_id=record.id)

    assert isinstance(recovered, RestoreRecovered)
    assert target.read_bytes() == b"current before restore"
    assert BackupRepository(root).list_restore_recoveries() == ()
    assert not tuple((device / ".iopenpod-recovery").glob("*"))


def test_recovery_finishes_a_restore_after_device_cleanup_wins_the_crash_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"selected")
    root = tmp_path / "backups"
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )
    captured = service.create_snapshot(root, _active(), max_backups=0)
    assert isinstance(captured, CaptureCreated)
    target.write_bytes(b"current before restore")
    native_clear = BackupRepository.clear_restore_recovery
    failed = False

    def fail_once(
        repository: BackupRepository,
        recovery_id: str,
        outcome: RestoreRecoveryOutcome,
    ) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated crash before Host recovery cleanup")
        native_clear(repository, recovery_id, outcome)

    with monkeypatch.context() as fault:
        fault.setattr(BackupRepository, "clear_restore_recovery", fail_once)
        incomplete = service.restore_snapshot(
            root,
            _active(),
            device_id=captured.snapshot.device_id,
            snapshot_id=captured.snapshot.id,
        )

    assert incomplete.kind == "restore.incomplete"
    assert target.read_bytes() == b"selected"
    assert not tuple((device / ".iopenpod-recovery").glob("*"))
    record = BackupRepository(root).list_restore_recoveries()[0]
    namespace = record.operation_journal.parent
    assert namespace is not None
    device.joinpath(*namespace.parts).mkdir(parents=True)

    recovered = service.recover_restore(root, _active(), recovery_id=record.id)

    assert isinstance(recovered, RestoreCompleted)
    assert recovered.snapshot_id == captured.snapshot.id
    assert target.read_bytes() == b"selected"
    assert BackupRepository(root).list_restore_recoveries() == ()
    assert not device.joinpath(*namespace.parts).exists()


def test_recovery_pin_failure_tells_the_user_how_to_unblock_the_archive() -> None:
    failure = backup_failure_for(
        BackupRecoveryRequiredError("snapshot is pinned"),
        operation="update_note",
    )

    assert failure.code is BackupFailureCode.ARCHIVE_BUSY
    assert "Restore Recovery" in failure.summary
    assert "run Restore Recovery" in failure.action


def test_corrupt_recovery_record_returns_a_typed_archive_failure(
    tmp_path: Path,
) -> None:
    device, _platform, session = _device_session(tmp_path)
    target = device / "file.bin"
    target.write_bytes(b"target")
    root = tmp_path / "backups"
    repository = BackupRepository(root)
    selected = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=_context().metadata,
    )
    assert selected is not None
    target.write_bytes(b"safety")
    safety = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=_context().metadata,
        reason=BackupReason.PRE_RESTORE_SAFETY,
        force=True,
    )
    assert safety is not None
    with repository.open_verified_snapshot(safety.device_id, safety.id) as verified:
        material_identity = verified.recovery_material_identity
    record = repository.begin_restore_recovery(
        target_archive_key=selected.device_id,
        safety_archive_key=safety.device_id,
        current_identity=_identity(),
        target_snapshot_id=selected.id,
        safety_snapshot_id=safety.id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )
    record_path = root / "v4" / "recoveries" / f"{record.id}.json"
    record_path.write_text("{}", encoding="utf-8")
    service = BackupService(
        cast("object", _Devices(_context(), session))  # type: ignore[arg-type]
    )

    outcome = service.recover_restore(root, _active(), recovery_id=record.id)

    assert isinstance(outcome, RestorePreMutationFailure)
    assert outcome.failure.code is BackupFailureCode.ARCHIVE_INVALID
    assert target.read_bytes() == b"safety"
