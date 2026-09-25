"""Public terminal-outcome contracts for Backup workflows."""

from pathlib import Path
from typing import assert_never

import pytest

from iOpenPod.app.backups.models import (
    BackupExportResult,
    BackupInventory,
    SnapshotInfo,
)
from iOpenPod.app.backups.outcomes import (
    BackupDiagnostic,
    BackupFailure,
    BackupFailureCode,
    BackupImportCounts,
    BrowseCancelled,
    BrowseCompleted,
    BrowseFailed,
    BrowseOutcome,
    CaptureCancelled,
    CaptureCreated,
    CaptureFailed,
    CaptureOutcome,
    CaptureUnchanged,
    DeviceWritePolicy,
    DisconnectGuidance,
    ExportCancelled,
    ExportCompleted,
    ExportFailed,
    ExportOutcome,
    FollowUpRequirement,
    ImportCancelled,
    ImportCompleted,
    ImportFailed,
    ImportOutcome,
    RestoreCancelled,
    RestoreCompleted,
    RestoreDurabilityPending,
    RestoreIncomplete,
    RestoreOutcome,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from storage import DevicePath, FlushResult


def _browse_label(outcome: BrowseOutcome) -> str:
    match outcome:
        case BrowseCompleted():
            return "completed"
        case BrowseCancelled():
            return "cancelled"
        case BrowseFailed():
            return "failed"
    assert_never(outcome)


def _capture_label(outcome: CaptureOutcome) -> str:
    match outcome:
        case CaptureCreated():
            return "created"
        case CaptureUnchanged():
            return "unchanged"
        case CaptureCancelled():
            return "cancelled"
        case CaptureFailed():
            return "failed"
    assert_never(outcome)


def _export_label(outcome: ExportOutcome) -> str:
    match outcome:
        case ExportCompleted():
            return "completed"
        case ExportCancelled():
            return "cancelled"
        case ExportFailed():
            return "failed"
    assert_never(outcome)


def _import_label(outcome: ImportOutcome) -> str:
    match outcome:
        case ImportCompleted():
            return "completed"
        case ImportCancelled():
            return "cancelled"
        case ImportFailed():
            return "failed"
    assert_never(outcome)


def _restore_label(outcome: RestoreOutcome) -> str:
    match outcome:
        case RestoreCompleted():
            return "completed"
        case RestoreUnchanged():
            return "unchanged"
        case RestoreRecovered():
            return "recovered"
        case RestoreDurabilityPending():
            return "durability-pending"
        case RestoreCancelled():
            return "cancelled"
        case RestorePreMutationFailure():
            return "pre-mutation-failure"
        case RestoreIncomplete():
            return "incomplete"
    assert_never(outcome)


def test_browse_completed_carries_one_immutable_inventory() -> None:
    inventory = BackupInventory(())

    outcome = BrowseCompleted(inventory)

    assert outcome.kind == "browse.completed"
    assert outcome.inventory is inventory


def test_browse_failure_exposes_a_stable_code_and_user_guidance() -> None:
    failure = BackupFailure(
        BackupFailureCode.ARCHIVE_INVALID,
        "The Backup Archive could not be trusted.",
        "Choose another archive or repair this one before retrying.",
        detail="manifest checksum mismatch",
    )

    outcome = BrowseFailed(failure)

    assert outcome.kind == "browse.failed"
    assert outcome.failure.code == "archive.invalid"
    assert outcome.failure.summary == "The Backup Archive could not be trusted."
    assert outcome.failure.action.startswith("Choose another archive")
    assert outcome.failure.detail == "manifest checksum mismatch"


def test_browse_outcome_is_an_exhaustive_terminal_union() -> None:
    failure = BackupFailure(BackupFailureCode.ARCHIVE_UNAVAILABLE, "Failed.", "Retry.")

    assert _browse_label(BrowseCompleted(BackupInventory(()))) == "completed"
    assert _browse_label(BrowseCancelled()) == "cancelled"
    assert _browse_label(BrowseFailed(failure)) == "failed"


def test_capture_distinguishes_a_created_snapshot_from_an_unchanged_device() -> None:
    snapshot = SnapshotInfo(
        "snapshot-1",
        "2026-09-12T12:00:00+00:00",
        "device-1",
        "RoadPod",
    )

    created = CaptureCreated(snapshot)
    unchanged = CaptureUnchanged(snapshot.id)

    assert created.kind == "capture.created"
    assert created.snapshot is snapshot
    assert unchanged.kind == "capture.unchanged"
    assert unchanged.snapshot_id == snapshot.id


def test_capture_outcome_is_an_exhaustive_terminal_union() -> None:
    snapshot = SnapshotInfo("s1", "today", "d1", "RoadPod")
    failure = BackupFailure(BackupFailureCode.SOURCE_CHANGED, "Failed.", "Retry.")

    assert _capture_label(CaptureCreated(snapshot)) == "created"
    assert _capture_label(CaptureUnchanged(snapshot.id)) == "unchanged"
    assert _capture_label(CaptureCancelled()) == "cancelled"
    assert _capture_label(CaptureFailed(failure)) == "failed"


def test_export_outcome_is_an_exhaustive_terminal_union() -> None:
    result = BackupExportResult(Path("exported"), 3, 42)
    failure = BackupFailure(
        BackupFailureCode.UNSAFE_DESTINATION,
        "The destination is unsafe.",
        "Choose another folder.",
    )

    completed = ExportCompleted(result)
    assert completed.result is result
    assert completed.kind == "export.completed"
    assert _export_label(completed) == "completed"
    assert _export_label(ExportCancelled()) == "cancelled"
    assert _export_label(ExportFailed(failure)) == "failed"


def test_import_completed_reports_new_and_already_present_content() -> None:
    diagnostic = BackupDiagnostic(
        "legacy.identity_unproven",
        "One imported snapshot needs confirmation before restore.",
    )

    outcome = ImportCompleted(
        imported=BackupImportCounts(devices=1, snapshots=3, content_items=8),
        already_present=BackupImportCounts(
            devices=1,
            snapshots=2,
            content_items=5,
        ),
        diagnostics=(diagnostic,),
    )

    assert outcome.kind == "import.completed"
    assert outcome.imported.snapshots == 3
    assert outcome.already_present.content_items == 5
    assert outcome.diagnostics == (diagnostic,)
    assert not hasattr(outcome, "source_unchanged")


def test_import_outcome_is_an_exhaustive_terminal_union() -> None:
    completed = ImportCompleted(BackupImportCounts(), BackupImportCounts())
    failure = BackupFailure(BackupFailureCode.ARCHIVE_INVALID, "Failed.", "Repair.")

    assert _import_label(completed) == "completed"
    assert _import_label(ImportCancelled()) == "cancelled"
    assert _import_label(ImportFailed(failure)) == "failed"


def test_restore_completed_is_proof_of_verified_durability() -> None:
    outcome = RestoreCompleted(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=True, detail="pending writes flushed"),
    )

    assert outcome.kind == "restore.completed"
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_writes is DeviceWritePolicy.BLOCKED_UNTIL_RELOAD
    assert outcome.follow_up.disconnect is DisconnectGuidance.STANDARD

    with pytest.raises(ValueError, match="complete durability barrier"):
        RestoreCompleted(
            "target-snapshot",
            "safety-snapshot",
            FlushResult(complete=False, detail="flush unavailable"),
        )


def test_restore_unchanged_allows_writes_without_a_reload_or_durability_claim() -> None:
    outcome = RestoreUnchanged("target-snapshot", "safety-snapshot")

    assert outcome.kind == "restore.unchanged"
    assert outcome.device_mutated is False
    assert outcome.content_verified is True
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.NONE
    assert outcome.follow_up.device_writes is DeviceWritePolicy.ALLOWED
    assert outcome.follow_up.disconnect is DisconnectGuidance.STANDARD
    assert _restore_label(outcome) == "unchanged"


def test_restore_recovered_is_verified_rollback_with_required_reload() -> None:
    outcome = RestoreRecovered(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=True, detail="recovery flushed"),
    )

    assert outcome.kind == "restore.recovered"
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_writes is DeviceWritePolicy.BLOCKED_UNTIL_RELOAD

    with pytest.raises(ValueError, match="complete durability barrier"):
        RestoreRecovered(
            "target-snapshot",
            "safety-snapshot",
            FlushResult(complete=False, detail="pending"),
        )


def test_restore_durability_pending_blocks_writes_and_requires_safe_eject() -> None:
    outcome = RestoreDurabilityPending(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=False, detail="flush unavailable"),
    )

    assert outcome.kind == "restore.durability_pending"
    assert outcome.content_verified is True
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.REQUIRED
    assert (
        outcome.follow_up.device_writes
        is DeviceWritePolicy.BLOCKED_UNTIL_DURABILITY_CONFIRMED
    )
    assert outcome.follow_up.disconnect is DisconnectGuidance.SAFE_EJECT_REQUIRED

    with pytest.raises(ValueError, match="incomplete durability barrier"):
        RestoreDurabilityPending(
            "target-snapshot",
            "safety-snapshot",
            FlushResult(complete=True, detail="pending writes flushed"),
        )


def test_restore_cancelled_guarantees_no_device_mutation_and_refreshes_if_needed() -> (
    None
):
    before_checkpoint = RestoreCancelled("target-snapshot")
    after_checkpoint = RestoreCancelled(
        "target-snapshot",
        safety_snapshot_id="safety-snapshot",
    )

    assert before_checkpoint.kind == "restore.cancelled"
    assert before_checkpoint.device_mutated is False
    assert before_checkpoint.safety_snapshot_id is None
    assert before_checkpoint.follow_up.archive_refresh is FollowUpRequirement.NONE
    assert after_checkpoint.device_mutated is False
    assert after_checkpoint.safety_snapshot_id == "safety-snapshot"
    assert after_checkpoint.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert after_checkpoint.follow_up.device_reload is FollowUpRequirement.NONE
    assert after_checkpoint.follow_up.device_writes is DeviceWritePolicy.ALLOWED


def test_restore_pre_mutation_failure_preserves_checkpoint_without_reloading() -> None:
    failure = BackupFailure(
        BackupFailureCode.INSUFFICIENT_SPACE,
        "There is not enough free space to restore this snapshot.",
        "Free space on the iPod and retry.",
    )

    outcome = RestorePreMutationFailure(
        "target-snapshot",
        failure,
        safety_snapshot_id="safety-snapshot",
    )

    assert outcome.kind == "restore.pre_mutation_failure"
    assert outcome.device_mutated is False
    assert outcome.failure is failure
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.NONE
    assert outcome.follow_up.device_writes is DeviceWritePolicy.ALLOWED


def test_restore_incomplete_requires_recovery_and_blocks_further_writes() -> None:
    failure = BackupFailure(
        BackupFailureCode.VERIFICATION_FAILED,
        "Restore stopped after changing the iPod.",
        "Recover from the retained journal before using the iPod.",
    )
    journal = DevicePath(".iopenpod-recovery/restore-1.json")

    outcome = RestoreIncomplete(
        "target-snapshot",
        "safety-snapshot",
        journal,
        failure,
    )

    assert outcome.kind == "restore.incomplete"
    assert outcome.device_mutated is True
    assert outcome.content_verified is False
    assert outcome.safety_snapshot_id == "safety-snapshot"
    assert outcome.recovery_journal == journal
    assert outcome.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_reload is FollowUpRequirement.REQUIRED
    assert outcome.follow_up.device_writes is DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
    assert outcome.follow_up.disconnect is DisconnectGuidance.SAFE_EJECT_REQUIRED

    with pytest.raises(ValueError, match="safety snapshot"):
        RestoreIncomplete("target-snapshot", "", journal, failure)

    assert _restore_label(outcome) == "incomplete"
    assert (
        _restore_label(
            RestoreCompleted(
                "target-snapshot",
                "safety-snapshot",
                FlushResult(True, "flushed"),
            )
        )
        == "completed"
    )
    assert (
        _restore_label(
            RestoreRecovered(
                "target-snapshot",
                "safety-snapshot",
                FlushResult(True, "recovered"),
            )
        )
        == "recovered"
    )
    assert (
        _restore_label(
            RestoreDurabilityPending(
                "target-snapshot",
                "safety-snapshot",
                FlushResult(False, "pending"),
            )
        )
        == "durability-pending"
    )
    assert _restore_label(RestoreCancelled("target-snapshot")) == "cancelled"
    assert (
        _restore_label(RestorePreMutationFailure("target-snapshot", failure))
        == "pre-mutation-failure"
    )
