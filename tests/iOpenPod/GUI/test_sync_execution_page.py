"""Sync outcomes expose actual diagnostics, cancellation, and recovery actions."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QProgressBar, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_write import WriteItemProgress, WriteProgress
from iOpenPod.app.media.progress import MediaPreparationPhase, MediaPreparationProgress
from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iOpenPod.GUI.widgets.sync_preparation_progress import SyncPreparationProgress
from iPodDB.library import IssueSeverity, WriteIssue


def test_concurrent_preparations_keep_independent_phase_progress_and_duplicate_titles() -> (
    None
):
    page = SyncExecutionPage()
    try:
        page.begin()
        converting = WriteItemProgress(
            "source-a",
            "Same title",
            MediaPreparationProgress(
                MediaPreparationPhase.CONVERTING, "Converting media", 30, 120, 2
            ),
        )
        verifying = WriteItemProgress(
            "source-b",
            "Same title",
            MediaPreparationProgress(
                MediaPreparationPhase.VERIFYING, "Verifying media", 75, 100, 10
            ),
        )
        page.update_progress(
            WriteProgress(
                "sync.prepare",
                "Preparing selected Tracks",
                completed=1,
                total=6,
                unit="Tracks",
                active_items=(converting, verifying),
            )
        )
        workers = page.findChild(SyncPreparationProgress, "syncPreparationProgressList")
        summary = page.findChild(QLabel, "syncPreparationSummary")
        assert workers is not None and summary is not None
        assert summary.text() == "2 active · 3 waiting · 1 processed"
        rows = workers.findChildren(QFrame, "syncPreparationRow")
        assert len(rows) == 2
        bars = workers.findChildren(QProgressBar, "syncPreparationProgress")
        assert [bar.value() for bar in bars] == [250, 750]
        details = [
            label.text()
            for label in workers.findChildren(QLabel, "syncPreparationDetail")
        ]
        assert "Converting media · 25% · 0:30 / 2:00 · 2.00x speed" in details
        assert "Verifying media · 75% · 1:15 / 1:40 · 10.00x speed" in details
        # A new phase has no invented percentage, even after conversion reaches 100%.
        reading = WriteItemProgress(
            "source-a",
            "Same title",
            MediaPreparationProgress(
                MediaPreparationPhase.METADATA, "Writing metadata"
            ),
        )
        page.update_progress(
            WriteProgress(
                "sync.prepare",
                "Preparing selected Tracks",
                completed=2,
                total=6,
                active_items=(reading,),
            )
        )
        bars = workers.findChildren(QProgressBar, "syncPreparationProgress")
        assert len(bars) == 1 and bars[0].maximum() == 0
        assert summary.text() == "1 active · 3 waiting · 2 processed"
        page.update_progress(WriteProgress("database.build", "Building Library"))
        assert workers.isHidden() and not workers.findChildren(
            QFrame, "syncPreparationRow"
        )
        assert summary.isHidden()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_active_rows_remain_visible_when_workers_are_replaced_and_can_scroll() -> None:
    page = SyncExecutionPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    page.resize(950, 650)
    try:
        page.begin()
        page.show()
        activity = MediaPreparationProgress(
            MediaPreparationPhase.CONVERTING, "Converting media", 30, 120
        )
        page.update_progress(
            WriteProgress(
                "sync.prepare",
                "Preparing",
                completed=0,
                total=20,
                active_items=(WriteItemProgress("first", "First Track", activity),),
            )
        )
        APPLICATION.processEvents()
        items = tuple(
            WriteItemProgress(str(index), f"Track {index}", activity)
            for index in range(16)
        )
        page.update_progress(
            WriteProgress(
                "sync.prepare", "Preparing", completed=1, total=20, active_items=items
            )
        )
        APPLICATION.processEvents()
        workers = page.findChild(SyncPreparationProgress, "syncPreparationProgressList")
        assert workers is not None
        rows = workers.findChildren(QFrame, "syncPreparationRow")
        assert len(rows) == 16 and all(row.isVisible() for row in rows)
        assert workers.verticalScrollBar().maximum() > 0
        workers.ensureWidgetVisible(rows[-1])
        APPLICATION.processEvents()
        position = rows[-1].mapTo(workers.viewport(), rows[-1].rect().center())
        assert workers.viewport().rect().contains(position)
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()


def test_measured_time_without_duration_is_indeterminate_and_result_clears_workers() -> (
    None
):
    page = SyncExecutionPage()
    try:
        page.begin()
        item = WriteItemProgress(
            "source",
            "Track",
            MediaPreparationProgress(
                MediaPreparationPhase.VERIFYING, "Verifying media", 45, None, 3
            ),
        )
        page.update_progress(
            WriteProgress(
                "sync.prepare", "Preparing", completed=0, total=1, active_items=(item,)
            )
        )
        workers = page.findChild(SyncPreparationProgress, "syncPreparationProgressList")
        assert workers is not None
        bar = workers.findChild(QProgressBar, "syncPreparationProgress")
        detail = workers.findChild(QLabel, "syncPreparationDetail")
        assert bar is not None and detail is not None
        assert bar.maximum() == 0
        assert "0:45 processed" in detail.text() and "%" not in detail.text()
        page.show_result(SyncExecutionResult(SyncExecutionStatus.CANCELLED))
        assert workers.isHidden() and not workers.findChildren(
            QProgressBar, "syncPreparationProgress"
        )
        page.begin()
        assert workers.isHidden()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


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
        assert summary.text() == "Step 3 of 7"
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


@pytest.mark.parametrize(
    "status", [SyncExecutionStatus.RECOVERY_REQUIRED, SyncExecutionStatus.SUCCESS]
)
def test_user_can_keep_current_contents_instead_of_recovery_or_cleanup(
    status: SyncExecutionStatus,
) -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                status,
                recovery_path=".iopenpod-recovery/" + "a" * 32 + "/transaction.json",
            )
        )
        keep = page.findChild(QPushButton, "keepSyncContents")
        recover = page.findChild(QPushButton, "recoverSyncExecution")
        assert keep is not None and recover is not None
        assert not keep.isHidden() and keep.text() == "Keep Current Contents"
        requested = QSignalSpy(page.keepContentsRequested)
        keep.click()
        assert requested.count() == 1
        page.begin_keep_contents()
        assert keep.isHidden() and recover.isHidden()
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=(WriteIssue("sync.kept_current", "Current contents kept."),),
            )
        )
        assert keep.isHidden() and recover.isHidden()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("count", [1, 2])
def test_completion_reports_the_applied_media_and_playlist_counts(count: int) -> None:
    page = SyncExecutionPage()
    try:
        item = SyncPlanItem(
            SyncPlanAction.REMOVE,
            SyncPlanMediaKind.TRACK,
            SyncPlanBasis.IPOD_ONLY,
            "Track",
            ipod_id=1,
        )
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                completed=(item,) * count,
                playlist_change_count=count,
            )
        )
        detail = page.findChild(QLabel, "syncExecutionDetail")
        assert detail is not None
        suffix = "" if count == 1 else "s"
        assert f"{count} selected change{suffix} committed." in detail.text()
        assert f"{count} Playlist{suffix} reconciled." in detail.text()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_language_change_retranslates_retained_progress_without_restarting_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr("iOpenPod.GUI.pages.sync_execution_page.monotonic", lambda: now)
    page = SyncExecutionPage()
    try:
        page.begin()
        page.update_progress(WriteProgress("sync.validate", "Validate"))
        page.update_progress(
            WriteProgress(
                "sync.prepare",
                "Preparing",
                completed=2,
                total=5,
                current_item="Track A",
            )
        )
        now += 10

        def translate(_page: SyncExecutionPage, text: str) -> str:
            return "Translated: " + text

        monkeypatch.setattr(SyncExecutionPage, "tr", translate)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        stage = page.findChild(QLabel, "syncExecutionStage")
        item = page.findChild(QLabel, "syncExecutionItem")
        elapsed = page.findChild(QLabel, "syncExecutionElapsed")
        activity = page.findChild(QPlainTextEdit, "syncExecutionActivity")
        progress = page.findChild(QProgressBar, "syncExecutionProgress")
        assert stage is not None and item is not None and elapsed is not None
        assert activity is not None and progress is not None
        assert stage.text() == "Translated: Prepare media on Host"
        assert item.text() == "Translated: Item: Track A"
        assert "10 s since the last progress update" in elapsed.text()
        assert activity.toPlainText() == (
            "Translated: Completed: Translated: Validate Sync Plan"
        )
        assert progress.value() == 2 and progress.maximum() == 5
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("operation", ["restore", "cleanup", "keep"])
def test_language_change_preserves_the_running_recovery_operation(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(SyncExecutionResult(SyncExecutionStatus.RECOVERY_REQUIRED))
        if operation == "keep":
            page.begin_keep_contents()
        else:
            page.begin_recovery(cleanup=operation == "cleanup")
        title = page.findChild(QLabel, "syncExecutionTitle")
        detail = page.findChild(QLabel, "syncExecutionDetail")
        assert title is not None and detail is not None
        original_title, original_detail = title.text(), detail.text()

        def translate(_page: SyncExecutionPage, text: str) -> str:
            return "Translated: " + text

        monkeypatch.setattr(SyncExecutionPage, "tr", translate)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert title.text() == "Translated: " + original_title
        assert detail.text() == "Translated: " + original_detail
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_formatted_progress_translates_template_before_inserting_user_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    language = "first"

    def translate(context: str, source: str, *_args: object) -> str:
        if context == "Workflow" and source == "Downloading {title}…":
            return "{title} — " + language
        if context == "Workflow" and source == "bytes":
            return "octets"
        return source

    monkeypatch.setattr(QCoreApplication, "translate", translate)
    page = SyncExecutionPage()
    try:
        message = source_text("Downloading {title}…", title="My {Podcast}")
        page.begin()
        page.update_progress(
            WriteProgress(
                "sync.podcast_download", message, completed=2, total=5, unit="bytes"
            )
        )
        detail = page.findChild(QLabel, "syncExecutionDetail")
        summary = page.findChild(QLabel, "syncExecutionProgressSummary")
        assert detail is not None and summary is not None
        assert detail.text() == "My {Podcast} — first"
        assert summary.text() == "2 of 5 octets"
        assert message == "Downloading My {Podcast}…"
        language = "second"
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert detail.text() == "My {Podcast} — second"
    finally:
        page.deleteLater()
        APPLICATION.processEvents()
