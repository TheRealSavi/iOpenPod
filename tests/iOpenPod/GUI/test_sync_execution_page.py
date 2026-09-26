"""Sync outcomes expose actual diagnostics, cancellation, and recovery actions."""

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QProgressBar, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iPodDB.library import IssueSeverity, WriteIssue


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


def test_progress_exposes_stage_counts_and_the_last_completed_item() -> None:
    page = SyncExecutionPage()
    try:
        page.begin()
        page.update_progress(
            WriteProgress(
                "sync.prepare",
                "Processed 13 of 57 Tracks; 0 messages.",
                completed=13,
                total=57,
                current_item="Track 13",
                unit="Tracks",
            )
        )
        stage = page.findChild(QLabel, "syncExecutionStage")
        summary = page.findChild(QLabel, "syncExecutionStageSummary")
        item = page.findChild(QLabel, "syncExecutionItem")
        progress = page.findChild(QProgressBar, "syncExecutionProgress")
        assert stage is not None and summary is not None and item is not None
        assert progress is not None
        assert stage.text() == "Prepare media on Host"
        assert summary.text() == "Step 2 of 6"
        assert item.text() == "Item: Track 13"
        assert progress.minimum() == 0
        assert progress.maximum() == 57
        assert progress.value() == 13
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_routine_conversion_notices_are_grouped_in_the_result() -> None:
    page = SyncExecutionPage()
    try:
        page.begin()
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                issues=tuple(
                    WriteIssue(
                        "sync.media_warning",
                        "Re-encoding a lossy source can reduce audio quality.",
                        severity=IssueSeverity.INFO,
                        artifact=f"book-{i}.m4b",
                    )
                    for i in range(5)
                ),
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        assert details.toPlainText().count("Re-encoding a lossy") == 1
        assert "5 items" in details.toPlainText()
        assert "INFO" in details.toPlainText()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_storage_progress_identifies_the_current_device_file() -> None:
    page = SyncExecutionPage()
    try:
        page.begin()
        page.update_progress(
            WriteProgress(
                "save.storage.publishing",
                "Publishing Library files: 4 of 9",
                completed=4,
                total=9,
                current_item="iPod_Control/iTunes/iTunesDB",
                unit="files",
            )
        )
        stage = page.findChild(QLabel, "syncExecutionStage")
        item = page.findChild(QLabel, "syncExecutionItem")
        progress = page.findChild(QProgressBar, "syncExecutionProgress")
        assert stage is not None and item is not None and progress is not None
        assert stage.text() == "Publish to iPod"
        assert item.text() == "Current file: iPod_Control/iTunes/iTunesDB"
        assert progress.value() == 4 and progress.maximum() == 9
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_recovery_progress_continues_after_cancellation_and_shows_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr("iOpenPod.GUI.pages.sync_execution_page.monotonic", lambda: now)
    page = SyncExecutionPage()
    try:
        page.begin()
        cancel = page.findChild(QPushButton, "cancelSyncExecution")
        assert cancel is not None
        cancel.click()
        page.update_progress(
            WriteProgress(
                "save.recovery.inspecting",
                "Reading recovery files…",
                completed=4,
                total=485,
                current_item="Music/file.m4a",
                unit="files",
            )
        )
        stage = page.findChild(QLabel, "syncExecutionStage")
        detail = page.findChild(QLabel, "syncExecutionDetail")
        elapsed = page.findChild(QLabel, "syncExecutionElapsed")
        bar = page.findChild(QProgressBar, "syncExecutionProgress")
        assert (
            stage is not None
            and detail is not None
            and elapsed is not None
            and bar is not None
        )
        assert stage.text() == "Recover previous Library"
        assert "Reading recovery files" in detail.text()
        assert "Cancellation requested" in detail.text()
        assert bar.value() == 4 and bar.maximum() == 485
        now += 65
        page._refresh_elapsed()  # pyright: ignore[reportPrivateUsage]
        assert "65 s since the last progress update" in elapsed.text()
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    WriteIssue(
                        "sync.restored_cleanup_pending",
                        "Originals restored; cleanup remains.",
                    ),
                ),
                recovery_path=".iopenpod-recovery/test/transaction.json",
            )
        )
        title = page.findChild(QLabel, "syncExecutionTitle")
        assert title is not None and "cleanup remains" in title.text()
        assert "restored and verified" in detail.text()
        assert not elapsed.text()
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
