"""Progress, cancellation, and durable outcomes for the selected Sync Plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.sync_execution import SyncExecutionResult, SyncExecutionStatus
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.library_write import WriteProgress


class SyncExecutionPage(QWidget):
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
        self._detail = QLabel(self)
        self._detail.setObjectName("syncExecutionDetail")
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._progress = QProgressBar(self)
        self._progress.setObjectName("syncExecutionProgress")
        self._progress.setRange(0, 0)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)
        layout.addWidget(self._progress)
        layout.addWidget(self._issues, 1)
        layout.addStretch()
        layout.addLayout(actions)
        self.retranslate_ui()

    def begin(self) -> None:
        self._result = None
        self._cancel_requested = False
        self._issues.clear()
        self._issues.hide()
        self._progress.setRange(0, 0)
        self._progress.show()
        self._cancel.setEnabled(True)
        self._cancel.show()
        self._done.hide()
        self._recover.hide()
        self._detail.setText(self.tr("Validating the selected Sync Plan…"))
        self.retranslate_ui()

    def update_progress(self, progress: WriteProgress) -> None:
        if not self._cancel_requested:
            self._detail.setText(progress.message)

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
        self._result = result
        self._progress.hide()
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
        self._recover.hide()
        self._done.hide()

    def retranslate_ui(self) -> None:
        self._cancel.setText(self.tr("Cancel Sync"))
        self._done.setText(self.tr("Return to Library"))
        self._recover.setText(self.tr("Retry Recovery"))
        self._issues.setAccessibleName(
            self.tr("Sync warnings, errors, and recovery steps")
        )
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
        if result.status is SyncExecutionStatus.RECOVERY_REQUIRED:
            detail += " " + self.tr(
                "Keep the recovery journal. Reconnect the same iPod and restore the "
                "interrupted Storage transaction before trying another Sync."
            )
        self._detail.setText(detail)
        lines = [
            f"{issue.severity.value.upper()} [{issue.code}] {issue.message}"
            + (f"\n{issue.detail}" if issue.detail else "")
            + (f"\n{issue.artifact}" if issue.artifact else "")
            for issue in result.issues
        ]
        if result.recovery_path:
            lines.append(self.tr("Recovery journal: ") + result.recovery_path)
        self._issues.setPlainText("\n\n".join(lines))
        self._issues.setVisible(bool(lines))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


__all__ = ["SyncExecutionPage"]
