"""Sync outcomes expose actual diagnostics, cancellation, and recovery actions."""

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iPodDB.library import WriteIssue


def test_cancel_reports_safe_checkpoint_and_prevents_double_request() -> None:
    page = SyncExecutionPage()
    try:
        page.begin()
        cancelled = QSignalSpy(page.cancelRequested)
        cancel = page.findChild(QPushButton, "cancelSyncExecution")
        detail = page.findChild(QLabel, "syncExecutionDetail")
        assert cancel is not None and detail is not None
        cancel.click()
        cancel.click()
        assert cancelled.count() == 1
        assert "Keep the iPod connected" in detail.text()
        assert not cancel.isEnabled()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_missing_tool_detail_and_recovery_path_are_visible() -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    WriteIssue(
                        "sync.failed",
                        "Sync stopped.",
                        detail="Install FFprobe and check PATH.",
                        artifact="Track A",
                    ),
                ),
                recovery_path=".iopenpod-recovery/test/transaction.json",
            )
        )
        text = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        recover = page.findChild(QPushButton, "recoverSyncExecution")
        assert text is not None and recover is not None
        assert "Install FFprobe and check PATH" in text.toPlainText()
        assert "Track A" in text.toPlainText()
        assert "transaction.json" in text.toPlainText()
        assert not recover.isHidden()
        requested = QSignalSpy(page.recoveryRequested)
        recover.click()
        assert requested.count() == 1
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_committed_cleanup_retry_is_distinct_from_restoring_previous_library() -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                recovery_path=".iopenpod-recovery/test/transaction.json",
            )
        )
        recover = page.findChild(QPushButton, "recoverSyncExecution")
        title = page.findChild(QLabel, "syncExecutionTitle")
        assert recover is not None and title is not None
        assert not recover.isHidden() and recover.text() == "Retry Cleanup"
        assert title.text() == "Sync completed"
        page.begin_recovery(cleanup=True)
        assert title.text() == "Cleaning up completed Sync"
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_playlist_only_completion_reports_the_applied_playlist_count() -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(SyncExecutionStatus.SUCCESS, playlist_change_count=2)
        )
        detail = page.findChild(QLabel, "syncExecutionDetail")
        assert detail is not None
        assert "2 Playlists reconciled" in detail.text()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()
