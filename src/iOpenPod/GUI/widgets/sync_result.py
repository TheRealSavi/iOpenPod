# Hallmark · component: Sync result · theme: iOpenPod · genre: modern-minimal
# structure: outcome · saved changes · messages · optional technical details
# pre-emit critique: P4 H5 E4 S5 R5 V4
"""A finished Sync outcome, separate from the running workflow's progress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import IssueSeverity

type SyncResultTone = Literal["success", "warning", "error", "neutral"]


@dataclass(frozen=True, slots=True)
class SyncResultMessage:
    """Translated user-facing text without diagnostic codes or journal paths."""

    severity: IssueSeverity
    text: str


class SyncResultView(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncResultView")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget(self)
        container.setObjectName("syncResultContainer")
        self.setWidget(container)
        centered = QHBoxLayout(container)
        centered.setContentsMargins(0, 0, 0, 0)
        content = QWidget(container)
        content.setObjectName("syncResultContent")
        content.setMaximumWidth(LAYOUT.sync_result_maximum_width)
        centered.addStretch()
        centered.addWidget(content, 1)
        centered.addStretch()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, LAYOUT.space_xs, LAYOUT.space_lg)
        layout.setSpacing(LAYOUT.space_lg)

        self._heading = QFrame(content)
        self._heading.setObjectName("syncResultHeading")
        heading_layout = QHBoxLayout(self._heading)
        heading_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        heading_layout.setSpacing(LAYOUT.space_md)
        self._symbol = QLabel(self._heading)
        self._symbol.setObjectName("syncResultSymbol")
        self._symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._symbol.setFixedSize(LAYOUT.space_3xl, LAYOUT.space_3xl)
        heading_layout.addWidget(self._symbol, 0, Qt.AlignmentFlag.AlignTop)
        heading_text = QVBoxLayout()
        heading_text.setSpacing(LAYOUT.space_xs)
        self.title = self._label("syncResultTitle", self._heading)
        self.description = self._label("syncResultDescription", self._heading)
        heading_text.addWidget(self.title)
        heading_text.addWidget(self.description)
        heading_layout.addLayout(heading_text, 1)
        layout.addWidget(self._heading)

        self.summary = self._label("syncResultSummary", content)
        layout.addWidget(self.summary)
        self._messages = QWidget(content)
        self._message_layout = QVBoxLayout(self._messages)
        self._message_layout.setContentsMargins(0, 0, 0, 0)
        self._message_layout.setSpacing(LAYOUT.space_md)
        layout.addWidget(self._messages)
        self._technical_toggle = ActionButton(
            parent=content, kind=ActionButtonKind.SECONDARY
        )
        self._technical_toggle.setObjectName("syncResultTechnicalToggle")
        self._technical_toggle.setCheckable(True)
        layout.addWidget(self._technical_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.technical_details = QPlainTextEdit(content)
        self.technical_details.setObjectName("syncExecutionIssues")
        self.technical_details.setReadOnly(True)
        self.technical_details.setMinimumHeight(LAYOUT.sync_result_details_height)
        self.technical_details.setMaximumHeight(LAYOUT.sync_result_details_height)
        self.technical_details.hide()
        self._technical_toggle.toggled.connect(self.technical_details.setVisible)
        layout.addWidget(self.technical_details)
        layout.addStretch()

    @staticmethod
    def _label(name: str, parent: QWidget) -> QLabel:
        label = QLabel(parent)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def reset(self) -> None:
        self._technical_toggle.setChecked(False)
        self.verticalScrollBar().setValue(0)

    def set_outcome(
        self, title: str, description: str, summary: str, tone: SyncResultTone
    ) -> None:
        self.title.setText(title)
        self.description.setText(description)
        self.summary.setText(summary)
        self.summary.setVisible(bool(summary))
        self._symbol.setText(
            {"success": "✓", "warning": "!", "error": "×"}.get(tone, "−")  # noqa: RUF001 -- visual status symbols
        )
        self._symbol.setAccessibleName(title)
        for widget in (self._heading, self._symbol):
            widget.setProperty("tone", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_messages(
        self,
        messages: tuple[SyncResultMessage, ...],
        headings: dict[IssueSeverity, str],
        empty_text: str,
        technical_text: str,
        technical_label: str,
    ) -> None:
        while (item := self._message_layout.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()
        for severity in (
            IssueSeverity.ERROR,
            IssueSeverity.WARNING,
            IssueSeverity.INFO,
        ):
            matching = [
                message.text for message in messages if message.severity is severity
            ]
            if not matching:
                continue
            section = QFrame(self._messages)
            section.setObjectName("syncResultMessageSection")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(
                LAYOUT.space_md, LAYOUT.space_sm, LAYOUT.space_md, LAYOUT.space_sm
            )
            section_layout.setSpacing(LAYOUT.space_sm)
            heading = self._label("syncResultMessageHeading", section)
            heading.setProperty("severity", severity.value)
            heading.setText(headings[severity])
            section_layout.addWidget(heading)
            for text in matching:
                message_label = self._label("syncResultMessage", section)
                message_label.setText(text)
                section_layout.addWidget(message_label)
            self._message_layout.addWidget(section)
        if not messages:
            empty = self._label("syncResultNoIssues", self._messages)
            empty.setText(empty_text)
            self._message_layout.addWidget(empty)
        self.technical_details.setPlainText(technical_text)
        self.technical_details.setAccessibleName(technical_label)
        self._technical_toggle.setText(technical_label)
        self._technical_toggle.setVisible(bool(technical_text))
        self.technical_details.setVisible(
            bool(technical_text) and self._technical_toggle.isChecked()
        )
