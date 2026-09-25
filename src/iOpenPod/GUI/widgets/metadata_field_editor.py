"""Reusable directly editable metadata field controls."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.metadata_fields import (
    FieldKind,
    MetadataField,
    display_value,
    parse_field,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import ContentAdvisory, MetadataValue, TrackChapter


class ChapterEditor(QWidget):
    """Edit a Track's ordered chapter markers."""

    def __init__(self, chapters: tuple[TrackChapter, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels([self.tr("Start (ms)"), self.tr("Title")])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setMinimumHeight(230)
        self.set_chapters(chapters)
        add = ActionButton(self.tr("Add chapter"), self)
        remove = ActionButton(
            self.tr("Remove selected"),
            self,
            kind=ActionButtonKind.DANGER,
        )
        sort = ActionButton(
            self.tr("Sort by time"),
            self,
            kind=ActionButtonKind.QUIET,
        )
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        sort.clicked.connect(self._sort)
        actions = QHBoxLayout()
        for button in (add, remove, sort):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(actions)

    def set_chapters(self, chapters: tuple[TrackChapter, ...]) -> None:
        self.table.setRowCount(len(chapters))
        for row, chapter in enumerate(chapters):
            self.table.setItem(row, 0, QTableWidgetItem(str(chapter.start_ms)))
            self.table.setItem(row, 1, QTableWidgetItem(chapter.title))

    def value(self) -> tuple[TrackChapter, ...]:
        result: list[TrackChapter] = []
        for row in range(self.table.rowCount()):
            start, title = self.table.item(row, 0), self.table.item(row, 1)
            if start is None or title is None:
                raise ValueError("Each chapter needs a start time and title.")
            result.append(TrackChapter(title.text(), int(start.text())))
        return tuple(result)

    def _add(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("0"))
        self.table.setItem(
            row, 1, QTableWidgetItem(self.tr("Chapter %1").replace("%1", str(row + 1)))
        )

    def _remove(self) -> None:
        for row in sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        ):
            self.table.removeRow(row)

    def _sort(self) -> None:
        try:
            self.set_chapters(
                tuple(sorted(self.value(), key=lambda chapter: chapter.start_ms))
            )
        except ValueError:
            self.table.setToolTip(self.tr("Enter numeric start times before sorting."))


class FieldEditor(QFrame):
    """One directly editable field that records whether the user changed it."""

    modifiedChanged = Signal()

    def __init__(
        self,
        spec: MetadataField,
        value: MetadataValue,
        mixed: bool,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.spec, self.initial, self.mixed = spec, value, mixed
        self._modified_state = False
        self._syncing = True
        self.setObjectName("metadataFieldRow")
        self.setProperty("modified", False)

        field_label = QLabel(spec.label, self)
        field_label.setObjectName("metadataFieldLabel")
        if spec.kind in (FieldKind.BOOLEAN, FieldKind.ADVISORY):
            editor = AppComboBox(self)
            if mixed:
                editor.addItem(self.tr("Mixed values"), None)
            options = (
                (("No", False), ("Yes", True))
                if spec.kind is FieldKind.BOOLEAN
                else tuple(
                    (advisory.value.capitalize(), advisory)
                    for advisory in ContentAdvisory
                )
            )
            for option_label, data in options:
                editor.addItem(option_label, data)
            editor.setCurrentIndex(0 if mixed else editor.findData(value))
            editor.currentIndexChanged.connect(self._modified)
            self.editor: QWidget = editor
        elif spec.kind is FieldKind.LONG_TEXT:
            long_editor = QPlainTextEdit(self)
            long_editor.setMaximumHeight(120)
            long_editor.setPlaceholderText(
                self.tr("Mixed values — unchanged") if mixed else ""
            )
            if not mixed:
                long_editor.setPlainText(str(value or ""))
            long_editor.textChanged.connect(self._modified)
            self.editor = long_editor
        elif spec.kind is FieldKind.CHAPTERS:
            chapters = value if isinstance(value, tuple) and not mixed else ()
            chapter_editor = ChapterEditor(chapters, self)
            chapter_editor.table.itemChanged.connect(self._modified)
            chapter_editor.table.model().rowsRemoved.connect(self._modified)
            self.editor = chapter_editor
        else:
            line = QLineEdit(self)
            line.setText("" if mixed else display_value(value, spec.kind))
            line.setPlaceholderText(
                self.tr("Mixed values — unchanged")
                if mixed
                else self.tr("ISO date or Unix seconds; blank to clear")
                if spec.kind is FieldKind.DATE
                else ""
            )
            line.textChanged.connect(self._modified)
            self.editor = line
        self.editor.setObjectName("field_" + spec.path)
        reset = ActionButton(
            self.tr("Reset"),
            self,
            kind=ActionButtonKind.QUIET,
        )
        reset.setObjectName("metadataFieldReset")
        reset.setVisible(False)
        reset.clicked.connect(self.reset)
        self.reset_button = reset
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(field_label)
        header.addStretch(1)
        header.addWidget(reset)
        layout.addLayout(header)
        layout.addWidget(self.editor)
        self._syncing = False

    def _modified(self, *_args: object) -> None:
        if self._syncing:
            return
        if (
            self.mixed
            and isinstance(self.editor, AppComboBox)
            and self.editor.currentData() is None
        ):
            self._set_modified(False)
            return
        self._set_modified(True)

    def is_modified(self) -> bool:
        return self._modified_state

    def _set_modified(self, modified: bool) -> None:
        if self._modified_state == modified:
            return
        self._modified_state = modified
        self.reset_button.setVisible(modified)
        self.setProperty("modified", modified)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()
        self.modifiedChanged.emit()

    def reset(self) -> None:
        self._syncing = True
        try:
            editor = self.editor
            if isinstance(editor, QLineEdit):
                editor.setText(
                    "" if self.mixed else display_value(self.initial, self.spec.kind)
                )
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlainText("" if self.mixed else str(self.initial or ""))
            elif isinstance(editor, AppComboBox):
                editor.setCurrentIndex(
                    0 if self.mixed else editor.findData(self.initial)
                )
            elif isinstance(editor, ChapterEditor):
                editor.set_chapters(
                    self.initial
                    if isinstance(self.initial, tuple) and not self.mixed
                    else ()
                )
        finally:
            self._syncing = False
        self._set_modified(False)

    def value(self) -> MetadataValue:
        editor = self.editor
        if isinstance(editor, QLineEdit):
            return parse_field(self.spec, editor.text())
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        if isinstance(editor, ChapterEditor):
            return editor.value()
        if isinstance(editor, AppComboBox):
            value: object = editor.currentData()
            if self.spec.kind is FieldKind.ADVISORY and isinstance(value, str):
                return ContentAdvisory(value)
            if isinstance(value, bool | ContentAdvisory):
                return value
            raise ValueError("Choose a value to replace mixed values.")
        raise ValueError("This field cannot be edited.")


__all__ = ["ChapterEditor", "FieldEditor"]
