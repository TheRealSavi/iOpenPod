"""Centralized, user-facing presentation for Backup workflow outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from PySide6.QtCore import QCoreApplication

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
from iOpenPod.GUI.presentation.i18n.text import english_count_fallback
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text

_LEGACY_IDENTITY_UNPROVEN = "legacy.identity_unproven"


class BackupMessages:
    """Provide a named Qt context whose plural calls lupdate can extract."""

    @staticmethod
    def tr(source_text: str, disambiguation: str, count: int) -> str:
        return QCoreApplication.translate(
            "BackupMessages", source_text, disambiguation, count
        )


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
                QCoreApplication.translate("BackupMessages", "Backups Refreshed"),
                english_count_fallback(
                    "Loaded backups for %n iPod(s).",
                    BackupMessages.tr(
                        "Loaded backups for %n iPod(s).", "", device_count
                    ),
                    device_count,
                ),
                QCoreApplication.translate(
                    "BackupMessages", "Select a Backup Snapshot to inspect or restore."
                ),
            )
        case BrowseCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate(
                    "BackupMessages", "Backup Refresh Cancelled"
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Refreshing stopped. The Backup Archive was not changed.",
                ),
                QCoreApplication.translate(
                    "BackupMessages", "Refresh again when you are ready."
                ),
            )
        case BrowseFailed(failure=failure):
            return _failure_message(
                QCoreApplication.translate("BackupMessages", "Could Not Load Backups"),
                failure,
            )
        case CaptureCreated(snapshot=snapshot):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                QCoreApplication.translate("BackupMessages", "Backup Complete"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "A verified Backup Snapshot was created for {snapshot_device_name}.",
                ).format(snapshot_device_name=snapshot.device_name),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Keep the Backup Archive available when you need to restore.",
                ),
            )
        case CaptureUnchanged(snapshot_id=snapshot_id):
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate("BackupMessages", "Backup Already Current"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "The iPod's file catalog still matches Backup Snapshot {snapshot_id}. No new Backup Snapshot was needed.",
                ).format(snapshot_id=snapshot_id),
                QCoreApplication.translate("BackupMessages", "No action is needed."),
            )
        case CaptureCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate("BackupMessages", "Backup Cancelled"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Backup creation was cancelled before a new snapshot was published. The iPod was not changed.",
                ),
                QCoreApplication.translate(
                    "BackupMessages", "Start a new backup when you are ready."
                ),
            )
        case CaptureFailed(failure=failure):
            return _failure_message(
                QCoreApplication.translate("BackupMessages", "Backup Failed"), failure
            )
        case ExportCompleted(result=result):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                QCoreApplication.translate("BackupMessages", "Export Complete"),
                english_count_fallback(
                    "Exported %n file(s) to {destination}.",
                    BackupMessages.tr(
                        "Exported %n file(s) to {destination}.", "", result.file_count
                    ),
                    result.file_count,
                ).format(destination=result.destination),
                QCoreApplication.translate(
                    "BackupMessages", "Keep the exported folder in a safe location."
                ),
            )
        case ExportCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate("BackupMessages", "Export Cancelled"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Export was cancelled. No partial export was left visible, and the Backup Snapshot was not changed.",
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Choose a destination and export again when you are ready.",
                ),
            )
        case ExportFailed(failure=failure):
            return _failure_message(
                QCoreApplication.translate("BackupMessages", "Export Failed"), failure
            )
        case ImportCompleted() as completed:
            return _import_completed_message(completed)
        case ImportCancelled():
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate("BackupMessages", "Legacy Import Cancelled"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Import was cancelled. The Original iOpenPod backup was not changed, and no new native Backup Snapshots were published.",
                ),
                QCoreApplication.translate(
                    "BackupMessages", "Start the import again when you are ready."
                ),
            )
        case ImportFailed(failure=failure):
            return _failure_message(
                QCoreApplication.translate("BackupMessages", "Import Failed"), failure
            )
        case RestoreCompleted(
            snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
        ):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                QCoreApplication.translate("BackupMessages", "Restore Complete"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Backup Snapshot {snapshot_id} was restored and verified. Its content was durably written to the iPod. Safety Snapshot: {safety_snapshot_id}.",
                ).format(
                    snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Wait for the iPod reload to finish before making further changes.",
                ),
            )
        case RestoreUnchanged(
            snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
        ):
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate(
                    "BackupMessages", "iPod Already Matches Backup"
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "The iPod already matches Backup Snapshot {snapshot_id}. No device write was attempted. Safety Snapshot: {safety_snapshot_id}.",
                ).format(
                    snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
                ),
                QCoreApplication.translate("BackupMessages", "No action is needed."),
            )
        case RestoreRecovered(
            snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
        ):
            return BackupMessage(
                BackupMessageSeverity.SUCCESS,
                QCoreApplication.translate(
                    "BackupMessages", "Restore Recovery Complete"
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "The interrupted restore of Backup Snapshot {snapshot_id} was rolled back and verified. The iPod matches Safety Snapshot {safety_snapshot_id}.",
                ).format(
                    snapshot_id=snapshot_id, safety_snapshot_id=safety_snapshot_id
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Wait for the iPod reload to finish before making further changes.",
                ),
            )
        case RestoreDurabilityPending(
            safety_snapshot_id=safety_snapshot_id, flush=flush
        ):
            return BackupMessage(
                BackupMessageSeverity.WARNING,
                QCoreApplication.translate(
                    "BackupMessages", "Restore Verified — Safe Eject Required"
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "The restored content was verified, but iOpenPod could not confirm that all pending writes reached the iPod. Safety Snapshot: {safety_snapshot_id}.",
                ).format(safety_snapshot_id=safety_snapshot_id),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Do not start another write. Use the operating system's safe eject before unplugging the iPod.",
                ),
                flush.detail,
            )
        case RestoreCancelled(safety_snapshot_id=safety_snapshot_id):
            safety_note = (
                QCoreApplication.translate(
                    "BackupMessages", " Safety Snapshot: {safety_snapshot_id}."
                ).format(safety_snapshot_id=safety_snapshot_id)
                if safety_snapshot_id is not None
                else ""
            )
            return BackupMessage(
                BackupMessageSeverity.INFO,
                QCoreApplication.translate("BackupMessages", "Restore Cancelled"),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Restore was cancelled before device changes began. The iPod was not changed.{safety_note}",
                ).format(safety_note=safety_note),
                QCoreApplication.translate(
                    "BackupMessages",
                    "You can retry the restore or choose another Backup Snapshot.",
                ),
            )
        case RestorePreMutationFailure(
            failure=failure, safety_snapshot_id=safety_snapshot_id
        ):
            safety_note = (
                QCoreApplication.translate(
                    "BackupMessages", " Safety Snapshot: {safety_snapshot_id}."
                ).format(safety_snapshot_id=safety_snapshot_id)
                if safety_snapshot_id is not None
                else ""
            )
            return _failure_message(
                QCoreApplication.translate(
                    "BackupMessages", "Restore Did Not Change the iPod"
                ),
                failure,
                body_suffix=QCoreApplication.translate(
                    "BackupMessages", "The iPod was not changed.{safety_note}"
                ).format(safety_note=safety_note),
            )
        case RestoreIncomplete(
            safety_snapshot_id=safety_snapshot_id,
            recovery_journal=recovery_journal,
            failure=failure,
        ):
            return BackupMessage(
                BackupMessageSeverity.ERROR,
                QCoreApplication.translate(
                    "BackupMessages", "Restore Incomplete — Recovery Required"
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "{failure_summary} The iPod's contents are not trusted. Safety Snapshot: {safety_snapshot_id}. Recovery Journal: {recovery_journal}.",
                ).format(
                    failure_summary=workflow_text(failure.summary),
                    safety_snapshot_id=safety_snapshot_id,
                    recovery_journal=recovery_journal,
                ),
                QCoreApplication.translate(
                    "BackupMessages",
                    "Keep the iPod connected. Do not use, sync, or write to it until recovery finishes. If you must disconnect it, use the operating system's safe eject.",
                ),
                _failure_diagnostic_detail(failure),
            )
    assert_never(outcome)


def _failure_message(
    title: str, failure: BackupFailure, *, body_suffix: str = ""
) -> BackupMessage:
    body = workflow_text(failure.summary)
    if body_suffix:
        body = f"{body} {body_suffix}"
    return BackupMessage(
        BackupMessageSeverity.ERROR,
        title,
        body,
        workflow_text(failure.action),
        _failure_diagnostic_detail(failure),
    )


def _failure_diagnostic_detail(failure: BackupFailure) -> str:
    code = QCoreApplication.translate(
        "BackupMessages", "Code: {failure_code_value}"
    ).format(failure_code_value=failure.code.value)
    return f"{code}\n{workflow_text(failure.detail)}" if failure.detail else code


def _import_completed_message(completed: ImportCompleted) -> BackupMessage:
    imported = completed.imported
    already_present = completed.already_present
    body = _import_counts_body(imported, already_present)
    body = " ".join(
        (
            body,
            QCoreApplication.translate(
                "BackupMessages", "The Original iOpenPod backup was not changed."
            ),
        )
    )
    diagnostic_detail = _diagnostics_detail(completed.diagnostics)
    needs_confirmation = any(
        diagnostic.code == _LEGACY_IDENTITY_UNPROVEN
        for diagnostic in completed.diagnostics
    )
    if needs_confirmation:
        return BackupMessage(
            BackupMessageSeverity.WARNING,
            QCoreApplication.translate(
                "BackupMessages", "Legacy Backups Imported — Confirmation Needed"
            ),
            QCoreApplication.translate(
                "BackupMessages",
                "{body} Some imported snapshots need identity confirmation before restore.",
            ).format(body=body),
            QCoreApplication.translate(
                "BackupMessages",
                "Connect the matching iPod and confirm its identity before restoring one of these snapshots.",
            ),
            diagnostic_detail,
        )
    if completed.diagnostics:
        return BackupMessage(
            BackupMessageSeverity.WARNING,
            QCoreApplication.translate(
                "BackupMessages", "Legacy Backups Imported with Warnings"
            ),
            QCoreApplication.translate(
                "BackupMessages", "{body} Import completed with warnings."
            ).format(body=body),
            QCoreApplication.translate(
                "BackupMessages",
                "Review the diagnostic details before using the imported snapshots.",
            ),
            diagnostic_detail,
        )
    if imported.snapshots == 0:
        return BackupMessage(
            BackupMessageSeverity.INFO,
            QCoreApplication.translate(
                "BackupMessages", "Legacy Backups Already Imported"
            ),
            body,
            QCoreApplication.translate("BackupMessages", "No action is needed."),
        )
    return BackupMessage(
        BackupMessageSeverity.SUCCESS,
        QCoreApplication.translate("BackupMessages", "Legacy Backups Imported"),
        body,
        QCoreApplication.translate(
            "BackupMessages",
            "Review the imported Backup Snapshots before restoring one.",
        ),
    )


def _import_counts_body(
    imported: BackupImportCounts, already_present: BackupImportCounts
) -> str:
    return " ".join(
        (
            english_count_fallback(
                "Imported %n Backup Snapshot(s).",
                BackupMessages.tr(
                    "Imported %n Backup Snapshot(s).", "", imported.snapshots
                ),
                imported.snapshots,
            ),
            english_count_fallback(
                "Imported %n content item(s).",
                BackupMessages.tr(
                    "Imported %n content item(s).", "", imported.content_items
                ),
                imported.content_items,
            ),
            english_count_fallback(
                "Read %n legacy iPod(s).",
                BackupMessages.tr("Read %n legacy iPod(s).", "", imported.devices),
                imported.devices,
            ),
            english_count_fallback(
                "%n Backup Snapshot(s) already present.",
                BackupMessages.tr(
                    "%n Backup Snapshot(s) already present.",
                    "",
                    already_present.snapshots,
                ),
                already_present.snapshots,
            ),
            english_count_fallback(
                "%n content item(s) already present.",
                BackupMessages.tr(
                    "%n content item(s) already present.",
                    "",
                    already_present.content_items,
                ),
                already_present.content_items,
            ),
        )
    )


def _diagnostics_detail(diagnostics: tuple[BackupDiagnostic, ...]) -> str:
    entries: list[str] = []
    for diagnostic in diagnostics:
        summary = workflow_text(diagnostic.summary)
        entry = f"{diagnostic.code}: {summary}"
        if diagnostic.detail:
            entry = f"{entry}\n{diagnostic.detail}"
        entries.append(entry)
    return "\n\n".join(entries)
