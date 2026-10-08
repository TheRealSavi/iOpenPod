"""Persistent, bounded scan diagnostics beside Host selection and Review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import HostMediaScanIssue


class HostScanIssues(QFrame):
    """Keep rejected sources visible without building an unbounded text widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hostScanIssues")
        self._issues: tuple[HostMediaScanIssue, ...] = ()
        self._summary = QLabel(self)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)
        self._toggle = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        self._toggle.setCheckable(True)
        self._details = QPlainTextEdit(self)
        self._details.setObjectName("hostScanIssueDetails")
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(140)
        self._details.hide()
        self._toggle.toggled.connect(self._details.setVisible)
        heading = QHBoxLayout()
        heading.addWidget(self._summary, 1)
        heading.addWidget(self._toggle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_xs, LAYOUT.space_lg, LAYOUT.space_xs
        )
        layout.addLayout(heading)
        layout.addWidget(self._details)
        self.retranslate_ui()

    @property
    def has_issues(self) -> bool:
        return bool(self._issues)

    def load(self, issues: tuple[HostMediaScanIssue, ...]) -> None:
        self._issues = issues
        self._toggle.setChecked(False)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._summary.setText(
            self.tr("Scan issues: {count}. Some media may be unavailable.").format(
                count=len(self._issues)
            )
        )
        self._toggle.setText(self.tr("Show details"))
        lines = [
            f"{str(issue.path)[:500]}\n{workflow_text(issue.detail)[:1500]}"
            for issue in self._issues[:50]
        ]
        if len(self._issues) > 50:
            lines.append(self.tr("Showing the first 50 scan issues."))
        self._details.setPlainText("\n\n".join(lines))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
