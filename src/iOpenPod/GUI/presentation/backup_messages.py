"""Centralized, user-facing presentation for Backup workflow outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from iOpenPod.app.backups.outcomes import (
    BackupDiagnostic,
    BackupFailure,
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

_LEGACY_IDENTITY_UNPROVEN = "legacy.identity_unproven"


class BackupMessageSeverity(StrEnum):
    """Visual urgency of a Backup message."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class BackupMessage:
    """Presentation-ready copy with optional expandable diagnostics."""

    severity: BackupMessageSeverity
    title: str
    body: str
    next_step: str
    diagnostic_detail: str = ""


def backup_message_for(outcome: BackupTerminalOutcome) -> BackupMessage:
    """Translate one terminal Backup outcome into the GUI's only copy catalog."""

    match outcome:
        case BrowseCompleted(inventory=inventory):
            device_count = len(inventory.devices)
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                "Backups Refreshed",
                f"Loaded backups for {device_count} {_plural(device_count, 'iPod')}.",
                "Select a Backup Snapshot to inspect or restore.",
            )
        case BrowseCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Backup Refresh Cancelled",
                "Refreshing stopped. The Backup Archive was not changed.",
                "Refresh again when you are ready.",
            )
        case BrowseFailed(failure=failure):
            return _failure_message("Could Not Load Backups", failure)
        case CaptureCreated(snapshot=snapshot):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                "Backup Complete",
                f"A verified Backup Snapshot was created for {snapshot.device_name}.",
                "Keep the Backup Archive available when you need to restore.",
            )
        case CaptureUnchanged(snapshot_id=snapshot_id):
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Backup Already Current",
                (
                    f"The iPod's file catalog still matches Backup Snapshot "
                    f"{snapshot_id}. No new Backup Snapshot was needed."
                ),
                "No action is needed.",
            )
        case CaptureCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Backup Cancelled",
                (
                    "Backup creation was cancelled before a new snapshot was "
                    "published. The iPod was not changed."
                ),
                "Start a new backup when you are ready.",
            )
        case CaptureFailed(failure=failure):
            return _failure_message("Backup Failed", failure)
        case ExportCompleted(result=result):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                "Export Complete",
                (
                    f"Exported {result.file_count} "
                    f"{_plural(result.file_count, 'file')} to {result.destination}."
                ),
                "Keep the exported folder in a safe location.",
            )
        case ExportCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Export Cancelled",
                (
                    "Export was cancelled. No partial export was left visible, "
                    "and the Backup Snapshot was not changed."
                ),
                "Choose a destination and export again when you are ready.",
            )
        case ExportFailed(failure=failure):
            return _failure_message("Export Failed", failure)
        case ImportCompleted() as completed:
            return _import_completed_message(completed)
        case ImportCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Legacy Import Cancelled",
                (
                    "Import was cancelled. The Original iOpenPod backup was not "
                    "changed, and no new native Backup Snapshots were published."
                ),
                "Start the import again when you are ready.",
            )
        case ImportFailed(failure=failure):
            return _failure_message("Import Failed", failure)
        case RestoreCompleted(
            snapshot_id=snapshot_id,
            safety_snapshot_id=safety_snapshot_id,
        ):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                "Restore Complete",
                (
                    f"Backup Snapshot {snapshot_id} was restored and verified. "
                    "Its content was durably written to the iPod. "
                    f"Safety Snapshot: {safety_snapshot_id}."
                ),
                "Wait for the iPod reload to finish before making further changes.",
            )
        case RestoreUnchanged(
            snapshot_id=snapshot_id,
            safety_snapshot_id=safety_snapshot_id,
        ):
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "iPod Already Matches Backup",
                (
                    f"The iPod already matches Backup Snapshot {snapshot_id}. "
                    "No device write was attempted. "
                    f"Safety Snapshot: {safety_snapshot_id}."
                ),
                "No action is needed.",
            )
        case RestoreRecovered(
            snapshot_id=snapshot_id,
            safety_snapshot_id=safety_snapshot_id,
        ):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                "Restore Recovery Complete",
                (
                    f"The interrupted restore of Backup Snapshot {snapshot_id} was "
                    "rolled back and verified. The iPod matches Safety Snapshot "
                    f"{safety_snapshot_id}."
                ),
                "Wait for the iPod reload to finish before making further changes.",
            )
        case RestoreDurabilityPending(
            safety_snapshot_id=safety_snapshot_id,
            flush=flush,
        ):
            return BackupMessage(
                BackupMessageSeverity.WARNING,
                "Restore Verified — Safe Eject Required",
                (
                    "The restored content was verified, but iOpenPod could not "
                    "confirm that all pending writes reached the iPod. "
                    f"Safety Snapshot: {safety_snapshot_id}."
                ),
                (
                    "Do not start another write. Use the operating system's safe "
                    "eject before unplugging the iPod."
                ),
                flush.detail,
            )
        case RestoreCancelled(safety_snapshot_id=safety_snapshot_id):
            safety_note = (
                f" Safety Snapshot: {safety_snapshot_id}."
                if safety_snapshot_id is not None
                else ""
            )
            return BackupMessage(
                BackupMessageSeverity.INFO,
                "Restore Cancelled",
                (
                    "Restore was cancelled before device changes began. "
                    f"The iPod was not changed.{safety_note}"
                ),
                "You can retry the restore or choose another Backup Snapshot.",
            )
        case RestorePreMutationFailure(
            failure=failure,
            safety_snapshot_id=safety_snapshot_id,
        ):
            safety_note = (
                f" Safety Snapshot: {safety_snapshot_id}."
                if safety_snapshot_id is not None
                else ""
            )
            return _failure_message(
                "Restore Did Not Change the iPod",
                failure,
                body_suffix=f"The iPod was not changed.{safety_note}",
            )
        case RestoreIncomplete(
            safety_snapshot_id=safety_snapshot_id,
            recovery_journal=recovery_journal,
            failure=failure,
        ):
            return BackupMessage(
                BackupMessageSeverity.ERROR,
                "Restore Incomplete — Recovery Required",
                (
                    f"{failure.summary} The iPod's contents are not trusted. "
                    f"Safety Snapshot: {safety_snapshot_id}. "
                    f"Recovery Journal: {recovery_journal}."
                ),
                (
                    "Keep the iPod connected. Do not use, sync, or write to it "
                    "until recovery finishes. If you must disconnect it, use the "
                    "operating system's safe eject."
                ),
                _failure_diagnostic_detail(failure),
            )
    assert_never(outcome)


def _failure_message(
    title: str,
    failure: BackupFailure,
    *,
    body_suffix: str = "",
) -> BackupMessage:
    body = failure.summary
    if body_suffix:
        body = f"{body} {body_suffix}"
    return BackupMessage(
        BackupMessageSeverity.ERROR,
        title,
        body,
        failure.action,
        _failure_diagnostic_detail(failure),
    )


def _failure_diagnostic_detail(failure: BackupFailure) -> str:
    code = f"Code: {failure.code.value}"
    return f"{code}\n{failure.detail}" if failure.detail else code


def _import_completed_message(completed: ImportCompleted) -> BackupMessage:
    imported = completed.imported
    already_present = completed.already_present
    body = _import_counts_body(imported, already_present)
    body += " The Original iOpenPod backup was not changed."
    diagnostic_detail = _diagnostics_detail(completed.diagnostics)
    needs_confirmation = any(
        diagnostic.code == _LEGACY_IDENTITY_UNPROVEN
        for diagnostic in completed.diagnostics
    )

    if needs_confirmation:
        return BackupMessage(
            BackupMessageSeverity.WARNING,
            "Legacy Backups Imported — Confirmation Needed",
            (
                f"{body} Some imported snapshots need identity confirmation "
                "before restore."
            ),
            (
                "Connect the matching iPod and confirm its identity before "
                "restoring one of these snapshots."
            ),
            diagnostic_detail,
        )

    if completed.diagnostics:
        return BackupMessage(
            BackupMessageSeverity.WARNING,
            "Legacy Backups Imported with Warnings",
            f"{body} Import completed with warnings.",
            "Review the diagnostic details before using the imported snapshots.",
            diagnostic_detail,
        )

    if imported.snapshots == 0:
        return BackupMessage(
            BackupMessageSeverity.INFO,
            "Legacy Backups Already Imported",
            body,
            "No action is needed.",
        )

    return BackupMessage(
        BackupMessageSeverity.SUCCESS,
        "Legacy Backups Imported",
        body,
        "Review the imported Backup Snapshots before restoring one.",
    )


def _import_counts_body(
    imported: BackupImportCounts,
    already_present: BackupImportCounts,
) -> str:
    imported_snapshot = _plural(imported.snapshots, "Backup Snapshot")
    imported_content = _plural(imported.content_items, "content item")
    legacy_device = _plural(imported.devices, "legacy iPod")
    existing_verb = "was" if already_present.snapshots == 1 else "were"
    existing_content = _plural(already_present.content_items, "content item")
    return (
        f"{imported.snapshots} {imported_snapshot} and {imported.content_items} "
        f"{imported_content} were imported from {imported.devices} {legacy_device}. "
        f"{already_present.snapshots} {existing_verb} already present, along with "
        f"{already_present.content_items} {existing_content}."
    )


def _diagnostics_detail(diagnostics: tuple[BackupDiagnostic, ...]) -> str:
    entries: list[str] = []
    for diagnostic in diagnostics:
        entry = f"{diagnostic.code}: {diagnostic.summary}"
        if diagnostic.detail:
            entry = f"{entry}\n{diagnostic.detail}"
        entries.append(entry)
    return "\n\n".join(entries)


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"
