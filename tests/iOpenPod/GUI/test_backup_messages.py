"""User-facing presentation for typed Backup workflow outcomes."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from iOpenPod.app.backups.models import (
    BackupDeviceInfo,
    BackupExportResult,
    BackupInventory,
    SnapshotInfo,
)
from iOpenPod.app.backups.outcomes import (
    BackupDiagnostic,
    BackupFailure,
    BackupFailureCode,
    BackupImportCounts,
    BackupTerminalOutcome,
    BrowseCancelled,
    BrowseCompleted,
    BrowseFailed,
    CaptureCancelled,
    CaptureCreated,
    CaptureFailed,
    CaptureUnchanged,
    ExportCancelled,
    ExportCompleted,
    ExportFailed,
    ImportCancelled,
    ImportCompleted,
    ImportFailed,
    RestoreCancelled,
    RestoreCompleted,
    RestoreDurabilityPending,
    RestoreIncomplete,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.GUI.presentation.backup_messages import (
    BackupMessageSeverity,
    backup_message_for,
)
from storage import DevicePath, FlushResult


def test_created_snapshot_becomes_an_immutable_success_message() -> None:
    outcome = CaptureCreated(SnapshotInfo("snapshot-1", "today", "device-1", "RoadPod"))

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.SUCCESS
    assert message.title == "Backup Complete"
    assert "RoadPod" in message.body
    assert "verified Backup Snapshot" in message.body
    assert message.next_step

    with pytest.raises(FrozenInstanceError):
        message.title = "Changed"  # type: ignore[misc]


def test_unchanged_capture_explains_that_no_snapshot_was_needed() -> None:
    message = backup_message_for(CaptureUnchanged("snapshot-1"))

    assert message.severity is BackupMessageSeverity.INFO
    assert message.title == "Backup Already Current"
    assert "snapshot-1" in message.body
    assert "No new Backup Snapshot was needed" in message.body
    assert message.next_step


def test_browse_and_export_successes_are_presented_without_gui_dependencies() -> None:
    inventory = BackupInventory(
        (BackupDeviceInfo("device-1", "RoadPod", snapshot_count=3),)
    )
    refreshed = backup_message_for(BrowseCompleted(inventory))
    exported = backup_message_for(
        ExportCompleted(BackupExportResult(Path("exports/RoadPod"), 27, 4096))
    )

    assert refreshed.severity is BackupMessageSeverity.SUCCESS
    assert refreshed.title == "Backups Refreshed"
    assert "1 iPod" in refreshed.body
    assert exported.severity is BackupMessageSeverity.SUCCESS
    assert exported.title == "Export Complete"
    assert "27 files" in exported.body
    assert "exports" in exported.body


def test_import_reports_new_and_already_present_legacy_snapshots() -> None:
    outcome = ImportCompleted(
        imported=BackupImportCounts(devices=1, snapshots=3, content_items=8),
        already_present=BackupImportCounts(
            devices=1,
            snapshots=2,
            content_items=5,
        ),
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.SUCCESS
    assert message.title == "Legacy Backups Imported"
    assert "3 Backup Snapshots" in message.body
    assert "2 Backup Snapshots already present" in message.body
    assert "Original iOpenPod backup was not changed" in message.body


def test_import_surfaces_legacy_restore_confirmation_without_raw_diagnostics() -> None:
    raw_detail = "parser at 0x7ffe: opaque internal identity error"
    outcome = ImportCompleted(
        imported=BackupImportCounts(devices=1, snapshots=1, content_items=2),
        already_present=BackupImportCounts(),
        diagnostics=(
            BackupDiagnostic(
                "legacy.identity_unproven",
                "Identity could not be proven from the legacy metadata.",
                raw_detail,
            ),
        ),
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.WARNING
    assert "Confirmation Needed" in message.title
    assert "confirmation" in message.body.lower()
    assert "matching iPod" in message.next_step
    assert raw_detail not in f"{message.title}{message.body}{message.next_step}"
    assert raw_detail in message.diagnostic_detail


@pytest.mark.parametrize(
    ("outcome", "expected_title"),
    [
        (BrowseFailed, "Could Not Load Backups"),
        (CaptureFailed, "Backup Failed"),
        (ExportFailed, "Export Failed"),
        (ImportFailed, "Import Failed"),
    ],
)
def test_operation_failures_keep_raw_details_out_of_primary_copy(
    outcome: type[BrowseFailed | CaptureFailed | ExportFailed | ImportFailed],
    expected_title: str,
) -> None:
    raw_detail = "PermissionError: C:\\private\\archive\\manifest.json"
    failure = BackupFailure(
        BackupFailureCode.ARCHIVE_UNAVAILABLE,
        "The Backup Archive is not available.",
        "Reconnect the backup drive and try again.",
        raw_detail,
    )

    message = backup_message_for(outcome(failure))

    assert message.severity is BackupMessageSeverity.ERROR
    assert message.title == expected_title
    assert failure.summary in message.body
    assert message.next_step == failure.action
    assert raw_detail not in f"{message.title}{message.body}{message.next_step}"
    assert raw_detail in message.diagnostic_detail
    assert failure.code.value in message.diagnostic_detail


def test_completed_restore_says_verification_and_durability_succeeded() -> None:
    outcome = RestoreCompleted(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=True, detail="pending writes flushed"),
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.SUCCESS
    assert message.title == "Restore Complete"
    assert "verified" in message.body
    assert "durably" in message.body
    assert "safety-snapshot" in message.body
    assert "reload" in message.next_step


def test_unchanged_restore_says_no_device_write_was_attempted() -> None:
    outcome = RestoreUnchanged("target-snapshot", "safety-snapshot")

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.INFO
    assert message.title == "iPod Already Matches Backup"
    assert "target-snapshot" in message.body
    assert "No device write was attempted" in message.body
    assert "safety-snapshot" in message.body
    assert message.next_step == "No action is needed."


def test_recovered_restore_says_the_target_was_rolled_back() -> None:
    outcome = RestoreRecovered(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=True, detail="recovery flushed"),
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.SUCCESS
    assert message.title == "Restore Recovery Complete"
    assert "rolled back" in message.body
    assert "safety-snapshot" in message.body


def test_pre_mutation_restore_failure_explicitly_says_ipod_is_unchanged() -> None:
    raw_detail = "OSError(28, 'No space left on device')"
    failure = BackupFailure(
        BackupFailureCode.INSUFFICIENT_SPACE,
        "There is not enough free space to restore this snapshot.",
        "Free space on the iPod and try again.",
        raw_detail,
    )
    outcome = RestorePreMutationFailure(
        "target-snapshot",
        failure,
        safety_snapshot_id="safety-snapshot",
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.ERROR
    assert message.title == "Restore Did Not Change the iPod"
    assert "The iPod was not changed" in message.body
    assert "safety-snapshot" in message.body
    assert message.next_step == failure.action
    assert raw_detail not in f"{message.title}{message.body}{message.next_step}"
    assert raw_detail in message.diagnostic_detail


def test_incomplete_restore_names_recovery_material_and_blocks_use() -> None:
    failure = BackupFailure(
        BackupFailureCode.VERIFICATION_FAILED,
        "Restored content could not be verified.",
        "Recover the interrupted restore.",
        "hash mismatch in file 14",
    )
    outcome = RestoreIncomplete(
        "target-snapshot",
        "safety-snapshot",
        DevicePath(".iopenpod-recovery/restore-1.json"),
        failure,
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.ERROR
    assert message.title == "Restore Incomplete — Recovery Required"
    assert "safety-snapshot" in message.body
    assert ".iopenpod-recovery/restore-1.json" in message.body
    assert "Keep the iPod connected" in message.next_step
    assert "Do not use, sync, or write to it" in message.next_step
    assert "safe eject" in message.next_step.lower()


def test_durability_pending_distinguishes_verified_content_from_pending_writes() -> (
    None
):
    raw_detail = "platform flush primitive unavailable: errno 95"
    outcome = RestoreDurabilityPending(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=False, detail=raw_detail),
    )

    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.WARNING
    assert message.title == "Restore Verified — Safe Eject Required"
    assert "content was verified" in message.body
    assert "could not confirm" in message.body
    assert "safety-snapshot" in message.body
    assert "safe eject" in message.next_step.lower()
    assert "Do not start another write" in message.next_step
    assert raw_detail not in f"{message.title}{message.body}{message.next_step}"
    assert raw_detail in message.diagnostic_detail


@pytest.mark.parametrize(
    "outcome",
    [
        BrowseCancelled(),
        CaptureCancelled(),
        ExportCancelled(),
        ImportCancelled(),
        RestoreCancelled("target-snapshot"),
        RestoreCancelled("target-snapshot", safety_snapshot_id="safety-snapshot"),
    ],
)
def test_cancellation_messages_explain_the_safe_terminal_state(
    outcome: BackupTerminalOutcome,
) -> None:
    message = backup_message_for(outcome)

    assert message.severity is BackupMessageSeverity.INFO
    assert "Cancelled" in message.title
    assert message.body
    assert message.next_step


def test_restore_cancellation_says_the_ipod_was_not_changed() -> None:
    message = backup_message_for(
        RestoreCancelled(
            "target-snapshot",
            safety_snapshot_id="safety-snapshot",
        )
    )

    assert "The iPod was not changed" in message.body
    assert "safety-snapshot" in message.body


def test_import_cancellation_reassures_that_the_legacy_source_is_unchanged() -> None:
    message = backup_message_for(ImportCancelled())

    assert "Original iOpenPod backup was not changed" in message.body
    assert "no new native Backup Snapshots" in message.body
