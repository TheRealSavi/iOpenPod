"""Page sentences use singular and plural forms for their actual item counts."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.test_backup_page import build_backup_page

from iOpenPod.app.backup_controller import BackupOperation
from iOpenPod.app.backups.models import BackupExportResult, SnapshotInfo
from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.pages.backup_page import BackupSnapshotCard
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iOpenPod.GUI.pages.sync_plan_page import SyncPlanPage
from iPodDB.library import WriteIssue


@pytest.mark.parametrize("count", [1, 2])
def test_sync_selection_and_extra_diagnostic_paths_use_count_forms(count: int) -> None:
    item = SyncPlanItem(
        SyncPlanAction.REMOVE,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.IPOD_ONLY,
        "Track",
        ipod_id=1,
    )
    review = SyncPlanPage()
    execution = SyncExecutionPage()
    try:
        review.load_plan(SyncPlan((item,) * count))
        suffix = "" if count == 1 else "s"
        assert (
            review.selection_summary
            == f"{count} of {count} media change{suffix} selected"
        )
        execution.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=tuple(
                    WriteIssue("failed", "Failed", artifact=f"file-{index}")
                    for index in range(count + 3)
                ),
            )
        )
        issues = execution.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert issues is not None
        assert f"…and {count} more file{suffix}" in issues.toPlainText()
    finally:
        review.deleteLater()
        execution.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("count", [1, 2])
def test_backup_details_and_export_use_file_count_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    shown: list[str] = []

    def show_dialog(dialog: QMessageBox) -> int:
        shown.append(dialog.informativeText())
        return 0

    def show_information(
        _parent: object, _title: str, body: str
    ) -> QMessageBox.StandardButton:
        shown.append(body)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", show_dialog)
    monkeypatch.setattr(QMessageBox, "information", show_information)
    card = BackupSnapshotCard(
        SnapshotInfo("snapshot", "today", "device", "iPod", file_count=count),
        can_restore=False,
        restore_hint="",
    )
    page, controller = build_backup_page(tmp_path)
    try:
        page.show()
        card._show_details()  # pyright: ignore[reportPrivateUsage]
        controller.operationCompleted.emit(
            BackupOperation.EXPORT, BackupExportResult(tmp_path, count, 0)
        )
        suffix = "" if count == 1 else "s"
        assert f"{count} file{suffix} · " in shown[0]
        assert shown[1] == f"Exported {count} file{suffix} to:\n\n{tmp_path}"
    finally:
        card.deleteLater()
        page.deleteLater()
        APPLICATION.processEvents()
