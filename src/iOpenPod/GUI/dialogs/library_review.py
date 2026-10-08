"""Change review and grouped, actionable preparation diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_write import LibraryFileChange
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.app.library_write_inspection import inspect_change
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)
from iPodDB.library import LibraryChange, WriteEffect, WriteIssue

if TYPE_CHECKING:
    from iOpenPod.app.library_write_controller import LibraryWriteController


class LibraryReviewDialog(QDialog):
    recordRequested = Signal(str, object)

    def __init__(
        self, controller: LibraryWriteController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("libraryReviewDialog")
        self.setWindowTitle(self.tr("Review Changes"))
        self.resize(760, 540)
        self._controller = controller
        self._status = QLabel(self)
        self._status.setObjectName("libraryReviewStatus")
        self._status.setWordWrap(True)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._items = QTreeWidget(self)
        self._items.setObjectName("libraryReviewItems")
        self._items.setHeaderLabels((self.tr("Change or issue"), self.tr("Record")))
        self._items.setColumnWidth(0, 460)
        self._details = QPlainTextEdit(self)
        self._details.setObjectName("libraryReviewDetails")
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(120)
        self._details.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        apply_action_button_kind(
            buttons.button(QDialogButtonBox.StandardButton.Close),
            ActionButtonKind.SECONDARY,
        )
        self._retry = ActionButton(self.tr("Prepare again"), self)
        self._cancel = ActionButton(self.tr("Cancel preparation"), self)
        self._discard = ActionButton(
            self.tr("Discard Changes"),
            self,
            kind=ActionButtonKind.DANGER,
        )
        self._discard.setObjectName("discardLibraryChanges")
        self._save = ActionButton(
            self.tr("Save to iPod"),
            self,
            kind=ActionButtonKind.PRIMARY,
        )
        self._save.setObjectName("savePlaylistsToIPod")
        self._inspect = ActionButton(
            self.tr("Inspect write…"),
            self,
            kind=ActionButtonKind.QUIET,
        )
        self._inspect.setObjectName("inspectLibraryWrite")
        buttons.addButton(self._inspect, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._save, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._retry, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._cancel, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._discard, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.rejected.connect(self.reject)
        self._retry.clicked.connect(controller.prepare)
        self._cancel.clicked.connect(controller.cancel)
        self._discard.clicked.connect(controller.discard_changes)
        self._save.clicked.connect(controller.save)
        self._inspect.clicked.connect(self._inspect_write)
        self._items.currentItemChanged.connect(self._selection_changed)
        self._items.itemDoubleClicked.connect(self._navigate)
        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(self._items, 1)
        layout.addWidget(self._details)
        layout.addWidget(buttons)
        controller.changed.connect(self.refresh)
        controller.progressChanged.connect(self._progress_changed)
        self.refresh()

    @Slot(object)
    def _progress_changed(self, message: object) -> None:
        if isinstance(message, str):
            self._status.setText(workflow_text(message))

    def refresh(self) -> None:
        state = self._controller.state
        messages = {
            PreparationState.IDLE: self.tr("Prepare changes for review."),
            PreparationState.PREPARING: self.tr("Preparing changes…"),
            PreparationState.READY: self.tr("Prepared for review."),
            PreparationState.BLOCKED: self.tr(
                "Output could not be prepared. Resolve the errors below and try again."
            ),
            PreparationState.STALE: self.tr(
                "This review is out of date. Prepare again to review current changes."
            ),
            PreparationState.CANCELLED: self.tr("Preparation cancelled."),
            PreparationState.FAILED: self.tr("Preparation failed."),
            PreparationState.SAVING: self.tr(
                "Saving Library changes… Keep the iPod connected until verification finishes."
            ),
            PreparationState.SAVED: self.tr(
                "Library changes saved and verified on your iPod."
            ),
            PreparationState.SAVE_FAILED: self.tr(
                "Saving did not complete successfully. See the details below."
            ),
        }
        self._status.setText(messages[state])
        self._progress.setVisible(
            state in (PreparationState.PREPARING, PreparationState.SAVING)
        )
        self._cancel.setVisible(state is PreparationState.PREPARING)
        self._retry.setEnabled(self._controller.can_prepare)
        self._discard.setVisible(self._controller.has_draft_changes)
        self._discard.setEnabled(self._controller.can_discard_changes)
        self._save.setVisible(
            state in (PreparationState.READY, PreparationState.SAVING)
        )
        self._save.setEnabled(self._controller.can_save)
        self._items.clear()
        self._details.hide()
        review = self._controller.review
        if review is None:
            return
        if review.plan:
            changes = QTreeWidgetItem(
                self._items,
                (self.tr("Changes (%1)").replace("%1", str(len(review.plan.changes))),),
            )
            for change in review.plan.changes:
                item = QTreeWidgetItem(
                    changes, (self._change_label(change), change.name)
                )
                item.setData(0, Qt.ItemDataRole.UserRole, change)
            changes.setExpanded(True)
            resolution = review.plan.resolution
            if resolution and resolution.effects:
                generated = QTreeWidgetItem(
                    self._items,
                    (
                        self.tr("Generated consequences (%1)").replace(
                            "%1", str(len(resolution.effects))
                        ),
                    ),
                )
                for effect in resolution.effects:
                    item = QTreeWidgetItem(
                        generated,
                        (
                            workflow_text(effect.reason),
                            self._record_label(effect.subject, effect.record_id),
                        ),
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, effect)
                generated.setExpanded(False)
        if review.file_changes:
            files = QTreeWidgetItem(
                self._items,
                (self.tr("Files (%1)").replace("%1", str(len(review.file_changes))),),
            )
            for file_change in review.file_changes:
                action = (
                    self.tr("Write")
                    if file_change.action == "write"
                    else self.tr("Move to recovery")
                    if file_change.action == "remove"
                    else self.tr("Delete permanently")
                )
                item = QTreeWidgetItem(files, (action, file_change.path))
                item.setData(0, Qt.ItemDataRole.UserRole, file_change)
                item.setToolTip(1, file_change.path)
            files.setExpanded(True)
        save = self._controller.save_result
        if save and save.recovery_path:
            recovery = QTreeWidgetItem(
                self._items, (self.tr("Recovery copy"), save.recovery_path)
            )
            recovery.setToolTip(1, save.recovery_path)
        for severity, label in (
            ("error", self.tr("Errors")),
            ("warning", self.tr("Warnings")),
        ):
            issues = tuple(
                issue
                for issue in (*review.result.issues, *(save.issues if save else ()))
                if issue.severity.value == severity
            )
            if not issues:
                continue
            group = QTreeWidgetItem(self._items, (f"{label} ({len(issues)})",))
            for issue in issues:
                subject = self._record_label(issue.subject, issue.record_id)
                item = QTreeWidgetItem(group, (workflow_text(issue.message), subject))
                item.setData(0, Qt.ItemDataRole.UserRole, issue)
                item.setToolTip(0, workflow_text(issue.message))
            group.setExpanded(True)

    def _change_label(self, change: LibraryChange) -> str:
        actions = {
            "add": self.tr("Add"),
            "edit": self.tr("Edit"),
            "delete": self.tr("Delete"),
        }
        return self.tr("{action} · {subject}").format(
            action=actions[change.action],
            subject=self._subject_label(change.subject),
        )

    def _subject_label(self, subject: str) -> str:
        return {
            "library": self.tr("Library"),
            "media": self.tr("Media"),
            "track": self.tr("Track"),
            "playlist": self.tr("Playlist"),
            "photo": self.tr("Photo"),
            "photo_album": self.tr("Photo Album"),
            "photos": self.tr("Photos"),
            "artwork": self.tr("Artwork"),
            "podcast": self.tr("Podcast"),
        }.get(subject, subject)

    def _record_label(self, subject: str, record_id: int | None) -> str:
        label = self._subject_label(subject)
        if record_id is None:
            return label
        return self.tr("{subject} {record_id}").format(
            subject=label, record_id=record_id
        )

    def _selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = None if current is None else current.data(0, Qt.ItemDataRole.UserRole)
        self._details.setVisible(
            isinstance(
                value, WriteIssue | LibraryChange | WriteEffect | LibraryFileChange
            )
        )
        if isinstance(value, WriteIssue):
            self._details.setPlainText(
                "\n".join(
                    part
                    for part in (
                        value.artifact,
                        value.field,
                        workflow_text(value.detail),
                        self.tr("Chunk {path} at {offset}").format(
                            path=value.chunk_path, offset=value.offset
                        )
                        if value.offset is not None
                        else "",
                    )
                    if part
                )
            )

        elif isinstance(value, LibraryFileChange):
            size = self.tr("%1 bytes").replace("%1", f"{value.size_bytes:,}")
            details = f"{value.path}\n{size}"
            if value.sha256 is not None:
                details += f"\nSHA-256: {value.sha256}"
            self._details.setPlainText(details)
        elif isinstance(value, LibraryChange):
            request, review = self._controller.request, self._controller.review
            self._details.setPlainText(
                inspect_change(value, request, review)
                if request is not None and review is not None
                else ", ".join(value.fields)
            )
        elif isinstance(value, WriteEffect):
            review = self._controller.review
            causes = (
                ()
                if review is None or review.plan is None
                else tuple(
                    review.plan.changes[i]
                    for i in value.causes
                    if 0 <= i < len(review.plan.changes)
                )
            )
            self._details.setPlainText(
                "\n".join(
                    (
                        value.code,
                        workflow_text(value.reason),
                        ", ".join(value.fields),
                        *tuple(
                            self.tr("Requested: {change} — {name} ({fields})").format(
                                change=self._change_label(c),
                                name=c.name,
                                fields=", ".join(c.fields),
                            )
                            for c in causes
                        ),
                    )
                )
            )

    def _inspect_write(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("libraryWriteInspection")
        dialog.setWindowTitle(self.tr("Write inspection"))
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            self.tr(
                "Captured developer report. Refresh to inspect current progress. Copied reports include Library metadata."
            ),
            dialog,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        text = QPlainTextEdit(dialog)
        text.setObjectName("libraryWriteInspectionJson")
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text.setPlainText(self._controller.inspection_json())
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        apply_action_button_kind(
            buttons.button(QDialogButtonBox.StandardButton.Close),
            ActionButtonKind.SECONDARY,
        )
        refresh = buttons.addButton(
            QCoreApplication.translate("CommonActions", "Refresh"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        copy = buttons.addButton(
            self.tr("Copy report"), QDialogButtonBox.ButtonRole.ActionRole
        )
        apply_action_button_kind(refresh, ActionButtonKind.SECONDARY)
        apply_action_button_kind(copy, ActionButtonKind.PRIMARY)
        refresh.clicked.connect(
            lambda: text.setPlainText(self._controller.inspection_json())
        )
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(text.toPlainText())
        )
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _navigate(self, item: QTreeWidgetItem, _column: int) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if (
            isinstance(value, WriteIssue | LibraryChange)
            and value.record_id is not None
        ):
            self.recordRequested.emit(value.subject, value.record_id)

    def reject(self) -> None:
        if self._controller.state is PreparationState.PREPARING:
            self._controller.cancel()
        super().reject()
