"""Sync outcomes expose actual diagnostics, cancellation, and recovery actions."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_write import WriteItemProgress, WriteProgress
from iOpenPod.app.media.progress import MediaPreparationPhase, MediaPreparationProgress
from iOpenPod.app.sync_diagnostics import describe_track_issues
from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iOpenPod.GUI.widgets.sync_preparation_progress import SyncPreparationProgress
from iPodDB.library import IssueSeverity, Track, WriteIssue


def test_success_replaces_cleanup_progress_with_a_finished_result() -> None:
    page = SyncExecutionPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    try:
        page.begin()
        page.show()
        page.update_progress(
            WriteProgress("sync.cleanup", "Cleaning up recovery files")
        )
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                issues=(
                    WriteIssue(
                        "sync.scrobble_pending",
                        "2 Tracks skipped.",
                        IssueSeverity.WARNING,
                    ),
                ),
            )
        )
        APPLICATION.processEvents()
        panel = page.findChild(QFrame, "syncExecutionPanel")
        stages = page.findChild(QFrame, "syncExecutionStages")
        assert panel is not None and not panel.isVisible()
        assert stages is not None and not stages.isVisible()
        title = page.findChild(QLabel, "syncResultTitle")
        heading = page.findChild(QFrame, "syncResultHeading")
        assert title is not None and title.isVisible()
        assert title.text() == "Sync completed successfully"
        assert heading is not None and heading.property("tone") == "success"
        assert all(
            label.property("state") == "complete"
            for label in stages.findChildren(QLabel)
        )
        page.update_progress(WriteProgress("sync.cleanup", "Late cleanup update"))
        assert page.showing_result and title.text() == "Sync completed successfully"
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize(
    ("status", "title_text", "tone"),
    (
        (SyncExecutionStatus.SUCCESS, "Sync completed successfully", "success"),
        (SyncExecutionStatus.PARTIAL, "Sync partially completed", "warning"),
        (SyncExecutionStatus.CANCELLED, "Sync cancelled", "neutral"),
        (SyncExecutionStatus.FAILED, "Sync could not complete", "error"),
        (SyncExecutionStatus.RECOVERY_REQUIRED, "Sync was interrupted", "error"),
    ),
)
def test_terminal_outcomes_replace_progress_and_allow_return_to_library(
    status: SyncExecutionStatus, title_text: str, tone: str
) -> None:
    page = SyncExecutionPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    try:
        page.begin()
        page.show()
        page.show_result(SyncExecutionResult(status))
        title = page.findChild(QLabel, "syncResultTitle")
        heading = page.findChild(QFrame, "syncResultHeading")
        cancel = page.findChild(QPushButton, "cancelSyncExecution")
        done = page.findChild(QPushButton, "finishSyncExecution")
        assert title is not None and title.text() == title_text and title.isVisible()
        assert heading is not None and heading.property("tone") == tone
        assert cancel is not None and not cancel.isVisible()
        assert done is not None and done.isVisible()
        requested = QSignalSpy(page.exitRequested)
        done.click()
        assert requested.count() == 1
        page.begin()
        assert not page.showing_result and cancel.isVisible() and not title.isVisible()
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()


def test_messages_are_grouped_by_severity_with_complete_expandable_details() -> None:
    page = SyncExecutionPage()
    try:
        warning = WriteIssue(
            "sync.warning", "Check this warning.", IssueSeverity.WARNING
        )
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.PARTIAL,
                issues=(
                    WriteIssue("sync.info", "A useful note.", IssueSeverity.INFO),
                    warning,
                    WriteIssue(
                        "sync.failed",
                        "A Track could not be synced.",
                        artifact="Track <one>",
                    ),
                    warning,
                ),
            )
        )
        headings = page.findChildren(QLabel, "syncResultMessageHeading")
        assert [label.text() for label in headings] == [
            "Errors (1)",
            "Warnings (1)",
            "Information (1)",
        ]
        messages = "\n".join(
            label.text() for label in page.findChildren(QLabel, "syncResultMessage")
        )
        assert "A useful note." in messages and "Check this warning." in messages
        assert "Track <one>" in messages and "sync.failed" not in messages
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        toggle = page.findChild(QPushButton, "syncResultTechnicalToggle")
        assert details is not None and details.isHidden() and toggle is not None
        assert "sync.failed" in details.toPlainText()
        toggle.click()
        assert not details.isHidden()
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert not details.isHidden()
        page.begin()
        page.show_result(SyncExecutionResult(SyncExecutionStatus.SUCCESS))
        assert details.isHidden() and toggle.isHidden()
        no_issues = page.findChild(QLabel, "syncResultNoIssues")
        assert no_issues is not None and "No warnings or errors" in no_issues.text()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("cleanup", [False, True])
def test_recovery_switches_back_to_running_view_until_its_result(cleanup: bool) -> None:
    page = SyncExecutionPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    try:
        page.show()
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS
                if cleanup
                else SyncExecutionStatus.RECOVERY_REQUIRED,
                recovery_path=".iopenpod-recovery/test/transaction.json",
            )
        )
        page.begin_recovery(cleanup=cleanup)
        assert not page.showing_result
        panel = page.findChild(QFrame, "syncExecutionPanel")
        assert panel is not None and panel.isVisible()
        page.update_progress(
            WriteProgress("save.recovery.inspecting", "Checking recovery files")
        )
        detail = page.findChild(QLabel, "syncExecutionDetail")
        assert detail is not None and "Checking recovery files" in detail.text()
        page.show_result(SyncExecutionResult(SyncExecutionStatus.SUCCESS))
        assert page.showing_result and not panel.isVisible()
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()


def test_long_results_scroll_without_hiding_the_return_action() -> None:
    page = SyncExecutionPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    page.resize(820, 540)
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.PARTIAL,
                issues=tuple(
                    WriteIssue(
                        "sync.failed",
                        f"Could not sync Track {index}.",
                        detail="Try this Track again.",
                    )
                    for index in range(40)
                ),
            )
        )
        page.show()
        APPLICATION.processEvents()
        result = page.findChild(QScrollArea, "syncResultView")
        done = page.findChild(QPushButton, "finishSyncExecution")
        assert result is not None and result.verticalScrollBar().maximum() > 0
        assert result.horizontalScrollBar().maximum() == 0
        assert done is not None and done.isVisible()
        assert page.rect().contains(done.geometry())
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()


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


def test_other_conversion_notices_are_grouped_in_the_result() -> None:
    page = SyncExecutionPage()
    try:
        page.begin()
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                issues=tuple(
                    WriteIssue(
                        "sync.media_warning",
                        "This iPod does not support ALAC. Preserved lossless audio as 16-bit WAV.",
                        severity=IssueSeverity.INFO,
                        artifact=f"book-{i}.m4b",
                    )
                    for i in range(5)
                ),
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        assert details.toPlainText().count("Preserved lossless audio") == 1
        assert "5 items" in details.toPlainText()
        assert "INFO" in details.toPlainText()
        assert "book-2.m4b" in details.toPlainText()
        assert "book-4.m4b" in details.toPlainText()
        message = page.findChild(QLabel, "syncResultMessage")
        assert message is not None and "book-3.m4b" not in message.text()
        assert "Technical details" in message.text()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize(
    ("code", "message"),
    (
        ("sync.media_warning", "Re-encoding a lossy source can reduce audio quality."),
        (
            "sync.podcast_media_warning",
            "Re-encoding a lossy source can reduce audio quality.",
        ),
        (
            "playlist.podcast_membership",
            "The special Podcasts playlist was updated to contain the resulting podcast Tracks.",
        ),
        (
            "playlist.podcast_group_order",
            "Podcast episodes were grouped by show; the prepared Playlist contains the resulting order.",
        ),
    ),
)
def test_routine_sync_notices_are_available_as_information(
    code: str, message: str
) -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                issues=(
                    WriteIssue(
                        code,
                        message,
                        severity=IssueSeverity.INFO,
                        artifact="https://publisher.example/episode.mp3",
                    ),
                ),
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        assert details.isHidden() and message in details.toPlainText()
        heading = page.findChild(QLabel, "syncResultMessageHeading")
        assert heading is not None and heading.text() == "Information (1)"
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert details.isHidden() and message in details.toPlainText()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_expected_notices_do_not_hide_other_podcast_diagnostics_or_recovery() -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.PARTIAL,
                issues=(
                    WriteIssue(
                        "playlist.podcast_membership",
                        "Membership updated",
                        IssueSeverity.INFO,
                    ),
                    WriteIssue(
                        "sync.podcast_media_warning",
                        "Output sample rate was adjusted.",
                        IssueSeverity.INFO,
                    ),
                    WriteIssue("sync.podcast_failed", "Episode download failed."),
                    WriteIssue(
                        "playlist.podcast_group_order",
                        "Cannot safely group episodes.",
                        IssueSeverity.WARNING,
                    ),
                ),
                recovery_path="iPod_Control/iOpenPod/recovery/journal.json",
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None and details.isHidden()
        text = details.toPlainText()
        assert "Membership updated" in text
        assert "Output sample rate was adjusted." in text
        assert "Episode download failed." in text
        assert "Cannot safely group episodes." in text
        assert "Recovery journal:" in text
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_error_groups_show_every_affected_file_and_ignore_repeated_diagnostics() -> (
    None
):
    page = SyncExecutionPage()
    try:
        issues = tuple(
            WriteIssue(
                "track.invalid_value",
                "Chapter positions must be ordered and fit within the Track duration.",
                subject="track",
                record_id=index,
                field="metadata.chapters",
                artifact=f"https://publisher.example/episode-{index}.mp3",
            )
            for index in range(5)
        )
        page.show_result(
            SyncExecutionResult(SyncExecutionStatus.FAILED, issues=issues + issues)
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        text = details.toPlainText()
        assert text.count("Chapter positions") == 1
        assert "5 items" in text and "10 items" not in text
        for issue in issues:
            assert text.count(issue.artifact) == 1
        assert "more files" not in text
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("diagnostic", ["", "Check the chapter positions."])
def test_unlabeled_errors_show_track_identity_and_field_and_retranslate(
    monkeypatch: pytest.MonkeyPatch,
    diagnostic: str,
) -> None:
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=(
                    WriteIssue(
                        "track.invalid_value",
                        "Chapter positions must be ordered and fit within the Track duration.",
                        subject="track",
                        record_id=-7,
                        field="metadata.chapters",
                        detail=diagnostic,
                    ),
                ),
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        assert "Track -7 · metadata.chapters" in details.toPlainText()

        def translate(_page: SyncExecutionPage, text: str, *_args: object) -> str:
            return "Titel %1" if text == "Track %1" else text

        monkeypatch.setattr(SyncExecutionPage, "tr", translate)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert "Titel -7 · metadata.chapters" in details.toPlainText()
        assert "Track -7" not in details.toPlainText()
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_episode_error_shows_publisher_label_and_enclosure_without_numeric_fallback() -> (
    None
):
    page = SyncExecutionPage()
    try:
        page.show_result(
            SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=(
                    WriteIssue(
                        "track.invalid_value",
                        "Chapter positions must be ordered and fit within the Track duration.",
                        subject="track",
                        record_id=-1,
                        detail="Episode {one} — My Podcast",
                        artifact="https://publisher.example/episode.mp3",
                    ),
                ),
            )
        )
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        text = details.toPlainText()
        assert "Episode {one} — My Podcast" in text
        assert "https://publisher.example/episode.mp3" in text
        assert "Track -1" not in text
    finally:
        page.deleteLater()
        APPLICATION.processEvents()


def test_track_diagnostic_keeps_a_user_title_matching_a_catalog_source_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title = "Untitled Track"
    track = Track(track_id=1, title=title, artist="", album="", length_ms=1000)
    issues = describe_track_issues(
        (
            WriteIssue(
                "track.invalid_value", "Invalid chapter", subject="track", record_id=1
            ),
        ),
        (track,),
    )

    def translate(context: str, source: str, *_args: object) -> str:
        if context == "Workflow" and source == title:
            return "Unbenannter Titel"
        return source

    monkeypatch.setattr(QCoreApplication, "translate", translate)
    page = SyncExecutionPage()
    try:
        page.show_result(SyncExecutionResult(SyncExecutionStatus.FAILED, issues=issues))
        details = page.findChild(QPlainTextEdit, "syncExecutionIssues")
        assert details is not None
        assert title in details.toPlainText()
        assert "Unbenannter Titel" not in details.toPlainText()
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
        title = page.findChild(QLabel, "syncResultTitle")
        assert title is not None and "cleanup remains" in title.text()
        description = page.findChild(QLabel, "syncResultDescription")
        assert description is not None and "restored and verified" in description.text()
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
        title = page.findChild(QLabel, "syncResultTitle")
        assert recover is not None and title is not None
        assert not recover.isHidden() and recover.text() == "Retry Cleanup"
        assert title.text() == "Sync completed successfully"
        page.begin_recovery(cleanup=True)
        progress_title = page.findChild(QLabel, "syncExecutionTitle")
        assert progress_title is not None
        assert progress_title.text() == "Cleaning up completed Sync"
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
        detail = page.findChild(QLabel, "syncResultSummary")
        assert detail is not None
        suffix = "" if count == 1 else "s"
        assert f"{count} change{suffix} saved to your iPod." in detail.text()
        assert f"{count} Playlist{suffix} updated." in detail.text()
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
