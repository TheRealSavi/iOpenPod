"""Progress, cancellation, and durable outcomes for the selected Sync Plan."""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.eta_label import EtaLabel
from iOpenPod.GUI.widgets.sync_preparation_progress import SyncPreparationProgress
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.library_write import WriteProgress


class SyncExecutionPage(QWidget):
    _STAGES = (
        ("sync.validate", "Validate Sync Plan"),
        ("sync.media", "Prepare media on Host"),
        ("database.", "Build and verify iPod Library"),
        ("save.", "Publish to iPod"),
        ("sync.helper", "Record Sync details"),
        ("sync.cleanup", "Clean up recovery files"),
    )

    cancelRequested = Signal()
    recoveryRequested = Signal()
    exitRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncExecutionPage")
        self._result: SyncExecutionResult | None = None
        self._cancel_requested = False
        self._title = QLabel(self)
        self._title.setObjectName("syncExecutionTitle")
        self._overall = QProgressBar(self)
        self._overall.setObjectName("syncExecutionOverallProgress")
        self._overall.setTextVisible(False)
        self._overall.setRange(0, len(self._STAGES))
        self._detail = QLabel(self)
        self._detail.setObjectName("syncExecutionDetail")
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._stage = QLabel(self)
        self._stage.setObjectName("syncExecutionStage")
        self._stage.setTextFormat(Qt.TextFormat.PlainText)
        self._stage.setWordWrap(True)
        self._stage_summary = QLabel(self)
        self._stage_summary.setObjectName("syncExecutionStageSummary")
        self._stage_summary.setTextFormat(Qt.TextFormat.PlainText)
        self._stage_summary.setWordWrap(True)
        self._stage_summary.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._stage_steps = tuple(QLabel(self) for _ in range(len(self._STAGES)))
        for index, label in enumerate(self._stage_steps, 1):
            label.setObjectName(f"syncExecutionStage{index}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setMinimumHeight(LAYOUT.control_height_large)
        self._item = QLabel(self)
        self._item.setObjectName("syncExecutionItem")
        self._item.setTextFormat(Qt.TextFormat.PlainText)
        self._item.setWordWrap(True)
        self._progress = QProgressBar(self)
        self._progress.setObjectName("syncExecutionProgress")
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress_summary = QLabel(self)
        self._progress_summary.setObjectName("syncExecutionProgressSummary")
        self._progress_summary.setTextFormat(Qt.TextFormat.PlainText)
        self._progress_summary.setWordWrap(True)
        self._eta = EtaLabel(self)
        self._eta.setObjectName("syncExecutionEta")
        self._preparation = SyncPreparationProgress(self)
        self._preparation_summary = QLabel(self)
        self._preparation_summary.setObjectName("syncPreparationSummary")
        self._preparation_summary.setWordWrap(True)
        self._preparation_summary.hide()
        self._elapsed = QLabel(self)
        self._elapsed.setObjectName("syncExecutionElapsed")
        self._elapsed.setWordWrap(True)
        self._phase_started = self._last_progress = monotonic()
        self._progress_phase = ""
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_elapsed)
        self._activity = QPlainTextEdit(self)
        self._activity.setObjectName("syncExecutionActivity")
        self._activity.setReadOnly(True)
        self._activity.setMaximumBlockCount(100)
        self._activity.setMinimumHeight(96)
        self._issues = QPlainTextEdit(self)
        self._issues.setObjectName("syncExecutionIssues")
        self._issues.setReadOnly(True)
        self._issues.setMaximumBlockCount(10_000)
        self._issues.hide()
        self._cancel = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        self._cancel.setObjectName("cancelSyncExecution")
        self._cancel.clicked.connect(self._request_cancel)
        self._done = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._done.setObjectName("finishSyncExecution")
        self._done.clicked.connect(self.exitRequested.emit)
        self._done.hide()
        self._recover = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._recover.setObjectName("recoverSyncExecution")
        self._recover.clicked.connect(self.recoveryRequested.emit)
        self._recover.hide()
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self._cancel)
        actions.addWidget(self._recover)
        actions.addWidget(self._done)

        stages = QFrame(self)
        stages.setObjectName("syncExecutionStages")
        stages_layout = QHBoxLayout(stages)
        stages_layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_xs,
            LAYOUT.space_sm,
            LAYOUT.space_xs,
        )
        stages_layout.setSpacing(LAYOUT.space_xs)
        for label in self._stage_steps:
            stages_layout.addWidget(label, 1)

        progress_panel = QFrame(self)
        progress_panel.setObjectName("syncExecutionPanel")
        panel_layout = QVBoxLayout(progress_panel)
        panel_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        panel_layout.setSpacing(LAYOUT.space_xs)
        panel_header = QHBoxLayout()
        panel_header.setSpacing(LAYOUT.space_sm)
        panel_header.addWidget(self._stage, 1)
        panel_header.addWidget(self._stage_summary)
        panel_layout.addLayout(panel_header)
        panel_layout.addWidget(self._detail)
        panel_layout.addWidget(self._item)
        panel_layout.addWidget(self._progress)
        panel_layout.addWidget(self._progress_summary)
        panel_layout.addWidget(self._eta)
        panel_layout.addWidget(self._preparation_summary)
        panel_layout.addWidget(self._preparation, 1)
        panel_layout.addWidget(self._elapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)
        layout.addWidget(self._title)
        layout.addWidget(self._overall)
        layout.addWidget(stages)
        layout.addWidget(progress_panel)
        layout.addWidget(self._activity)
        layout.addWidget(self._issues, 1)
        layout.addStretch()
        layout.addLayout(actions)
        self._active_stage: int | None = None
        self.retranslate_ui()

    def begin(self) -> None:
        self._phase_started = self._last_progress = monotonic()
        self._progress_phase = ""
        self._elapsed.clear()
        self._clock.start()
        self._result = None
        self._cancel_requested = False
        self._issues.clear()
        self._issues.hide()
        self._activity.clear()
        self._activity.show()
        self._set_stage(None)
        self._overall_progress_reset()
        self._progress.setRange(0, 0)
        self._progress.setFormat("")
        self._progress_summary.setText(self.tr("Waiting for the first action…"))
        self._item.clear()
        self._item.hide()
        self._eta.reset()
        self._preparation.set_items(())
        self._preparation_summary.hide()
        self._progress.show()
        self._cancel.setEnabled(True)
        self._cancel.show()
        self._done.hide()
        self._recover.hide()
        self._stage.setText(self.tr("Waiting to validate the selected Sync Plan"))
        self._stage_summary.setText(
            self.tr("Step 1 of %1").replace("%1", str(len(self._STAGES)))
        )
        self._detail.setText(self.tr("The Sync is starting. Keep the iPod connected."))
        self.retranslate_ui()

    def update_progress(self, progress: WriteProgress) -> None:
        stage_index = self._stage_index(progress.phase)
        self._set_stage(stage_index)
        title = self._STAGES[stage_index][1]
        if progress.phase.startswith("save.recovery."):
            title = "Recover previous Library"
        self._stage.setText(self.tr(title))
        self._stage_summary.setText(
            self.tr("Step %1 of %2")
            .replace("%1", str(stage_index + 1))
            .replace("%2", str(len(self._STAGES)))
        )
        message = progress.message
        if self._cancel_requested:
            message += " " + self.tr(
                "Cancellation requested; waiting for a safe stopping point. Keep the iPod connected."
            )
        self._detail.setText(message)
        now = monotonic()
        if self._progress_phase != progress.phase:
            self._progress_phase = progress.phase
            self._phase_started = now
        self._last_progress = now
        self._refresh_elapsed()
        if progress.total is not None and progress.total > 0:
            completed = max(0, min(progress.completed or 0, progress.total))
            self._progress.setRange(0, progress.total)
            self._progress.setValue(completed)
            unit = progress.unit or self.tr("items")
            self._progress_summary.setText(
                self.tr("%1 of %2 %3")
                .replace("%1", f"{completed:,}")
                .replace("%2", f"{progress.total:,}")
                .replace("%3", unit)
            )
            self._eta.set_progress(
                progress.phase,
                completed,
                progress.total,
                unit=unit,
            )
        else:
            self._progress.setRange(0, 0)
            self._progress_summary.setText(
                self.tr("This stage is working; its total is not item-counted.")
            )
            self._eta.reset()
        preparing = progress.phase == "sync.prepare"
        self._activity.setVisible(not preparing and self._result is None)
        self._preparation.set_items(progress.active_items if preparing else ())
        self._preparation_summary.setVisible(preparing)
        if preparing:
            active = len(progress.active_items)
            waiting = max(0, (progress.total or 0) - (progress.completed or 0) - active)
            self._preparation_summary.setText(
                self.tr("%1 active · %2 waiting · %3 processed")
                .replace("%1", str(active))
                .replace("%2", str(waiting))
                .replace("%3", str(progress.completed or 0))
            )
        if progress.current_item and not (preparing and progress.active_items):
            label = (
                self.tr("Item: %1")
                if progress.phase in ("sync.prepare", "sync.photos")
                else self.tr("Current file: %1")
            )
            self._item.setText(label.replace("%1", progress.current_item))
            self._item.show()
        else:
            self._item.clear()
            self._item.hide()

    def _refresh_elapsed(self) -> None:
        now = monotonic()
        self._elapsed.setText(
            self.tr("%1 s in this step · %2 s since the last progress update")
            .replace("%1", f"{max(0, int(now - self._phase_started)):,}")
            .replace("%2", f"{max(0, int(now - self._last_progress)):,}")
        )

    def _request_cancel(self) -> None:
        self._cancel_requested = True
        self._cancel.setEnabled(False)
        self._detail.setText(
            self.tr(
                "Cancellation requested. Waiting for a safe stopping point. "
                "If publication has started, Sync finishes the protected commit. "
                "Keep the iPod connected."
            )
        )
        self.cancelRequested.emit()

    def show_result(self, result: SyncExecutionResult) -> None:
        self._clock.stop()
        self._elapsed.clear()
        self._result = result
        self._progress.hide()
        self._eta.reset()
        self._preparation.set_items(())
        self._preparation_summary.hide()
        self._item.hide()
        self._activity.hide()
        if result.status in (SyncExecutionStatus.SUCCESS, SyncExecutionStatus.PARTIAL):
            self._set_stage(len(self._STAGES))
        self._cancel.hide()
        self._done.show()
        self._recover.setVisible(
            result.status is SyncExecutionStatus.RECOVERY_REQUIRED
            or (
                result.status
                in (SyncExecutionStatus.SUCCESS, SyncExecutionStatus.PARTIAL)
                and bool(result.recovery_path)
            )
        )
        self.retranslate_ui()

    def begin_recovery(self, *, cleanup: bool = False) -> None:
        self._title.setText(
            self.tr("Cleaning up completed Sync")
            if cleanup
            else self.tr("Restoring the previous Library")
        )
        self._detail.setText(
            self.tr("Removing verified recovery files. Keep the iPod connected.")
            if cleanup
            else self.tr(
                "Checking the journal and restoring the interrupted changes. Keep the iPod connected."
            )
        )
        self._progress.show()
        self._progress.setRange(0, 0)
        self._progress.setFormat("")
        self._progress_summary.setText(self.tr("Working through the recovery journal…"))
        self._item.hide()
        self._activity.hide()
        self._eta.reset()
        self._preparation.set_items(())
        self._preparation_summary.hide()
        self._recover.hide()
        self._done.hide()

    def retranslate_ui(self) -> None:
        self._cancel.setText(self.tr("Cancel Sync"))
        self._done.setText(self.tr("Return to Library"))
        self._recover.setText(self.tr("Retry Recovery"))
        self._issues.setAccessibleName(
            self.tr("Sync warnings, errors, and recovery steps")
        )
        self._set_stage(self._active_stage)
        result = self._result
        if result is None:
            self._title.setText(self.tr("Syncing the selected changes"))
            return
        if result.status in (SyncExecutionStatus.SUCCESS, SyncExecutionStatus.PARTIAL):
            self._recover.setText(self.tr("Retry Cleanup"))
        titles = {
            SyncExecutionStatus.SUCCESS: self.tr("Sync completed"),
            SyncExecutionStatus.PARTIAL: self.tr("Sync partially completed"),
            SyncExecutionStatus.CANCELLED: self.tr("Sync cancelled"),
            SyncExecutionStatus.FAILED: self.tr("Sync could not complete"),
            SyncExecutionStatus.RECOVERY_REQUIRED: self.tr("Sync needs recovery"),
        }
        self._title.setText(titles[result.status])
        if any(issue.code == "sync.recovered" for issue in result.issues):
            self._title.setText(self.tr("Previous Library restored"))
        restored_cleanup = any(
            issue.code == "sync.restored_cleanup_pending" for issue in result.issues
        )
        if restored_cleanup:
            self._title.setText(self.tr("Previous Library restored — cleanup remains"))
        detail = self.tr("%1 selected changes committed.").replace(
            "%1", f"{len(result.completed):,}"
        )
        if result.playlist_change_count:
            detail += " " + self.tr("%1 Playlists reconciled.").replace(
                "%1", f"{result.playlist_change_count:,}"
            )
        if result.status is SyncExecutionStatus.PARTIAL:
            detail += " " + self.tr(
                "The remaining items were skipped. Resolve the issues below and scan again."
            )
        elif result.status is SyncExecutionStatus.CANCELLED:
            detail += " " + self.tr("Scan again when you are ready to retry.")
        elif result.status is SyncExecutionStatus.FAILED:
            detail += " " + self.tr("Resolve the errors below, then scan again.")
        if restored_cleanup:
            detail = self.tr(
                "The previous Library was restored and verified. Keep the journal and retry recovery to finish removing its temporary files."
            )
        elif result.status is SyncExecutionStatus.RECOVERY_REQUIRED:
            detail += " " + self.tr(
                "Keep the recovery journal. Reconnect the same iPod and restore the "
                "interrupted Storage transaction before trying another Sync."
            )
        self._detail.setText(detail)
        grouped: dict[tuple[str, str, str, str], list[str]] = {}
        for issue in result.issues:
            key = (issue.severity.value, issue.code, issue.message, issue.detail)
            grouped.setdefault(key, []).append(issue.artifact)
        lines: list[str] = []
        for (severity, code, message, diagnostic), artifacts in grouped.items():
            count = f" ({len(artifacts):,} items)" if len(artifacts) > 1 else ""
            line = f"{severity.upper()} [{code}] {message}{count}"
            if diagnostic:
                line += "\n" + diagnostic
            paths = [path for path in artifacts if path]
            if paths:
                line += "\n" + "\n".join(paths[:3])
                if len(paths) > 3:
                    line += "\n" + self.tr("…and %1 more files").replace(
                        "%1", str(len(paths) - 3)
                    )
            lines.append(line)
        if result.recovery_path:
            lines.append(self.tr("Recovery journal: ") + result.recovery_path)
        self._issues.setPlainText("\n\n".join(lines))
        self._issues.setVisible(bool(lines))

    def _stage_index(self, phase: str) -> int:
        if phase == "sync.prepare" or phase == "sync.photos":
            return 1
        for index, (prefix, _title) in enumerate(self._STAGES):
            if phase == prefix or phase.startswith(prefix):
                return index
        return self._active_stage if self._active_stage is not None else 0

    def _set_stage(self, stage_index: int | None) -> None:
        previous = self._active_stage
        if stage_index is not None and previous is not None and stage_index != previous:
            self._activity.appendPlainText(
                self.tr("Completed: %1").replace(
                    "%1", self.tr(self._STAGES[previous][1])
                )
            )
        self._active_stage = stage_index
        for index, label in enumerate(self._stage_steps):
            if stage_index is None:
                state, marker = "pending", "○"
            elif index < stage_index:
                state, marker = "complete", "✓"
            elif index == stage_index:
                state, marker = "current", "●"
            else:
                state, marker = "pending", "○"
            label.setProperty("state", state)
            label.setText(f"{marker} {index + 1}\n{self.tr(self._STAGES[index][1])}")
            label.style().unpolish(label)
            label.style().polish(label)
        if stage_index is not None:
            self._overall.setValue(min(stage_index, len(self._STAGES)))

    def _overall_progress_reset(self) -> None:
        self._overall.setRange(0, len(self._STAGES))
        self._overall.setValue(0)
        self._overall.setTextVisible(False)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


__all__ = ["SyncExecutionPage"]
