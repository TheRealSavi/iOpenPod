"""Durable Host anchors for bounded Storage restore recovery."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

import iOpenPod.app.backups.repository as repository_module
from iOpenPod.app.backups import (
    BackupDeviceIdentity,
    BackupDeviceMetadata,
    BackupError,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupReason,
    BackupRecoveryRequiredError,
    BackupRepository,
    RestoreRecoveryOutcome,
    RestoreRecoveryPhase,
)
from iOpenPod.app.backups.recovery import encode_recovery
from storage import AccessMode, DevicePath, Storage
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from pathlib import Path


def _identity() -> BackupDeviceIdentity:
    return BackupDeviceIdentity(
        (
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                "SERIAL",
            ),
        )
    )


def _repository_with_snapshots(
    tmp_path: Path,
) -> tuple[BackupRepository, str, str, str, str]:
    device = tmp_path / "ipod"
    device.mkdir()
    target = device / "file.bin"
    target.write_bytes(b"target")
    platform = VirtualStoragePlatform()
    platform.add_volume(device, filesystem_type="fat32")
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    )
    repository = BackupRepository(tmp_path / "repository")
    selected = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=BackupDeviceMetadata(),
    )
    assert selected is not None
    target.write_bytes(b"current")
    safety = repository.create_snapshot(
        session,
        identity=_identity(),
        device_name="RoadPod",
        metadata=BackupDeviceMetadata(),
        reason=BackupReason.PRE_RESTORE_SAFETY,
        force=True,
    )
    assert safety is not None
    with repository.open_verified_snapshot(
        selected.device_id, safety.id
    ) as verified_safety:
        material_identity = verified_safety.recovery_material_identity
    return repository, selected.device_id, selected.id, safety.id, material_identity


def test_restore_recovery_is_durable_and_pins_safety_snapshot(tmp_path: Path) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )

    record = repository.begin_restore_recovery(
        target_archive_key=archive_key,
        safety_archive_key=archive_key,
        current_identity=_identity(),
        target_snapshot_id=target_id,
        safety_snapshot_id=safety_id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )

    assert record.phase is RestoreRecoveryPhase.SAFETY_PINNED
    assert record.outcome is RestoreRecoveryOutcome.UNRESOLVED
    recovery_path = tmp_path / "repository" / "v4" / "recoveries" / f"{record.id}.json"
    recovery_document = cast(
        "dict[str, object]", json.loads(recovery_path.read_text(encoding="utf-8"))
    )
    assert recovery_document["version"] == 4
    reopened = BackupRepository(tmp_path / "repository")
    assert reopened.list_restore_recoveries() == (record,)
    with pytest.raises(BackupRecoveryRequiredError, match="pins"):
        reopened.delete_snapshot(archive_key, safety_id)
    with pytest.raises(BackupRecoveryRequiredError, match="pins"):
        reopened.update_note(archive_key, safety_id, "Do not invalidate recovery")

    advanced = reopened.advance_restore_recovery(
        record.id, RestoreRecoveryPhase.DEVICE_TRANSACTION_PUBLISHED
    )

    assert advanced.operation_journal == record.operation_journal
    with pytest.raises(BackupError, match="Unresolved"):
        reopened.clear_restore_recovery(record.id, RestoreRecoveryOutcome.UNRESOLVED)
    reopened.clear_restore_recovery(
        record.id, RestoreRecoveryOutcome.VERIFIED_COMPLETION
    )
    assert reopened.list_restore_recoveries() == ()
    reopened.delete_snapshot(archive_key, safety_id)


def test_corrupt_restore_recovery_record_fails_closed(tmp_path: Path) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )
    record = repository.begin_restore_recovery(
        target_archive_key=archive_key,
        safety_archive_key=archive_key,
        current_identity=_identity(),
        target_snapshot_id=target_id,
        safety_snapshot_id=safety_id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )
    path = tmp_path / "repository" / "v4" / "recoveries" / f"{record.id}.json"
    document = cast("dict[str, object]", json.loads(path.read_text()))
    document["phase"] = RestoreRecoveryPhase.VERIFYING.value
    path.write_text(json.dumps(document))

    with pytest.raises(BackupError, match="checksum"):
        repository.list_restore_recoveries()
    with pytest.raises(BackupError, match="checksum"):
        repository.delete_snapshot(archive_key, safety_id)


def test_terminal_restore_recovery_is_reconciled_after_a_cleanup_crash(
    tmp_path: Path,
) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )
    record = repository.begin_restore_recovery(
        target_archive_key=archive_key,
        safety_archive_key=archive_key,
        current_identity=_identity(),
        target_snapshot_id=target_id,
        safety_snapshot_id=safety_id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )
    terminal = replace(
        record,
        outcome=RestoreRecoveryOutcome.VERIFIED_COMPLETION,
        updated_at="2026-09-12T12:30:00+00:00",
    )
    path = tmp_path / "repository" / "v4" / "recoveries" / f"{record.id}.json"
    path.write_bytes(encode_recovery(terminal))

    assert BackupRepository(tmp_path / "repository").list_restore_recoveries() == ()
    assert not path.exists()


def test_restore_recovery_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )
    record = repository.begin_restore_recovery(
        target_archive_key=archive_key,
        safety_archive_key=archive_key,
        current_identity=_identity(),
        target_snapshot_id=target_id,
        safety_snapshot_id=safety_id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )
    path = tmp_path / "repository" / "v4" / "recoveries" / f"{record.id}.json"
    encoded = path.read_text(encoding="utf-8")
    path.write_text(
        encoded.replace(
            '  "format": "iopenpod.backup.restore-recovery",',
            '  "format": "duplicate",\n  "format": "iopenpod.backup.restore-recovery",',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupError, match="Duplicate JSON field"):
        repository.list_restore_recoveries()


def test_restore_recovery_is_bounded_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )
    monkeypatch.setattr(repository_module, "_MAX_RECOVERY_RECORD_BYTES", 32)

    with pytest.raises(BackupError, match="exceeds its supported size"):
        repository.begin_restore_recovery(
            target_archive_key=archive_key,
            safety_archive_key=archive_key,
            current_identity=_identity(),
            target_snapshot_id=target_id,
            safety_snapshot_id=safety_id,
            operation_journal=DevicePath(
                ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
            ),
            recovery_material_identity=material_identity,
        )

    recoveries = tmp_path / "repository" / "v4" / "recoveries"
    assert tuple(recoveries.iterdir()) == ()


def test_restore_recovery_model_requires_an_exact_transaction_journal(
    tmp_path: Path,
) -> None:
    repository, archive_key, target_id, safety_id, material_identity = (
        _repository_with_snapshots(tmp_path)
    )
    record = repository.begin_restore_recovery(
        target_archive_key=archive_key,
        safety_archive_key=archive_key,
        current_identity=_identity(),
        target_snapshot_id=target_id,
        safety_snapshot_id=safety_id,
        operation_journal=DevicePath(
            ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
        ),
        recovery_material_identity=material_identity,
    )

    with pytest.raises(ValueError, match="exact transaction journal"):
        replace(record, operation_journal=DevicePath("other.json"))
