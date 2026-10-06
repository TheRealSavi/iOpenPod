"""Reusable directly editable metadata field controls."""

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QEvent, Signal
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
    MetadataFieldValue,
    display_value,
    parse_field,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import ContentAdvisory, MediaType, MetadataValue, TrackChapter

_MEDIA_TYPE_LABELS = {
    MediaType.AUDIO: str(QT_TRANSLATE_NOOP("FieldEditor", "Music")),
    MediaType.VIDEO: str(QT_TRANSLATE_NOOP("FieldEditor", "Movie")),
    MediaType.AUDIOBOOK: str(QT_TRANSLATE_NOOP("FieldEditor", "Audiobook")),
    MediaType.PODCAST: str(QT_TRANSLATE_NOOP("FieldEditor", "Podcast")),
    MediaType.VIDEO_PODCAST: str(QT_TRANSLATE_NOOP("FieldEditor", "Video Podcast")),
    MediaType.TV_SHOW: str(QT_TRANSLATE_NOOP("FieldEditor", "TV Show")),
    MediaType.MUSIC_VIDEO: str(QT_TRANSLATE_NOOP("FieldEditor", "Music Video")),
    MediaType.AUDIO_VIDEO: str(QT_TRANSLATE_NOOP("FieldEditor", "Audio and video")),
    MediaType.RINGTONE: str(QT_TRANSLATE_NOOP("FieldEditor", "Ringtone")),
    MediaType.RENTAL: str(QT_TRANSLATE_NOOP("FieldEditor", "Rental")),
    MediaType.ITUNES_EXTRA: str(QT_TRANSLATE_NOOP("FieldEditor", "iTunes Extras")),
    MediaType.MEMO: str(QT_TRANSLATE_NOOP("FieldEditor", "Voice Memo")),
    MediaType.ITUNES_U: "iTunes U",
    MediaType.EPUB_BOOK: str(QT_TRANSLATE_NOOP("FieldEditor", "EPUB Book")),
    MediaType.PDF_BOOK: str(QT_TRANSLATE_NOOP("FieldEditor", "PDF Book")),
}


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
        self._add_button = ActionButton(self.tr("Add chapter"), self)
        self._remove_button = ActionButton(
            self.tr("Remove selected"),
            self,
            kind=ActionButtonKind.DANGER,
        )
        self._sort_button = ActionButton(
            self.tr("Sort by time"),
            self,
            kind=ActionButtonKind.QUIET,
        )
        self._add_button.clicked.connect(self._add)
        self._remove_button.clicked.connect(self._remove)
        self._sort_button.clicked.connect(self._sort)
        actions = QHBoxLayout()
        for button in (self._add_button, self._remove_button, self._sort_button):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(actions)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.table.setHorizontalHeaderLabels(
                [self.tr("Start (ms)"), self.tr("Title")]
            )
            self._add_button.setText(self.tr("Add chapter"))
            self._remove_button.setText(self.tr("Remove selected"))
            self._sort_button.setText(self.tr("Sort by time"))
        super().changeEvent(event)

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
                raise ValueError(self.tr("Each chapter needs a start time and title."))
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
        value: MetadataFieldValue,
        mixed: bool,
        parent: QWidget,
        *,
        media_type_choices: tuple[MediaType, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.spec, self.initial, self.mixed = spec, value, mixed
        self._media_type_choices = media_type_choices
        self._modified_state = False
        self._syncing = True
        self.setObjectName("metadataFieldRow")
        self.setProperty("modified", False)

        field_label = QLabel(
            QCoreApplication.translate("MetadataFields", spec.label), self
        )
        self._field_label = field_label
        field_label.setObjectName("metadataFieldLabel")
        if spec.kind is FieldKind.MEDIA_TYPE:
            media_editor = AppComboBox(self)
            current = (
                value[0]
                if isinstance(value, tuple) and len(value) == 1 and not mixed
                else None
            )
            if mixed:
                media_editor.addItem(
                    QCoreApplication.translate("EditorLabels", "Mixed values"), None
                )
            elif current not in media_type_choices:
                retained = (
                    " + ".join(
                        self.tr(_MEDIA_TYPE_LABELS.get(kind, kind.value))
                        for kind in value
                        if isinstance(kind, MediaType)
                    )
                    if isinstance(value, tuple)
                    else str(value)
                )
                media_editor.addItem(
                    self.tr("Current (%1)").replace("%1", retained), None
                )
            for kind in media_type_choices:
                media_editor.addItem(self.tr(_MEDIA_TYPE_LABELS[kind]), kind.value)
            media_editor.setCurrentIndex(
                media_editor.findData(current) if current in media_type_choices else 0
            )
            media_editor.setEnabled(bool(media_type_choices))
            media_editor.setToolTip(
                self.tr(
                    "Changes Library classification; keeps the existing media file."
                )
                if media_type_choices
                else self.tr(
                    "Select audio Tracks or video Tracks with a known media type "
                    "to change their classification together."
                )
            )
            media_editor.currentIndexChanged.connect(self._modified)
            self.editor: QWidget = media_editor
        elif spec.kind in (FieldKind.BOOLEAN, FieldKind.ADVISORY):
            editor = AppComboBox(self)
            if mixed:
                editor.addItem(
                    QCoreApplication.translate("EditorLabels", "Mixed values"), None
                )
            options = (
                ((self.tr("No"), False), (self.tr("Yes"), True))
                if spec.kind is FieldKind.BOOLEAN
                else (
                    (self.tr("Unspecified"), ContentAdvisory.UNSPECIFIED),
                    (self.tr("Explicit"), ContentAdvisory.EXPLICIT),
                    (self.tr("Clean"), ContentAdvisory.CLEAN),
                )
            )
            for option_label, data in options:
                editor.addItem(option_label, data)
            editor.setCurrentIndex(0 if mixed else editor.findData(value))
            editor.currentIndexChanged.connect(self._modified)
            self.editor = editor
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
            chapters = (
                tuple(chapter for chapter in value if isinstance(chapter, TrackChapter))
                if isinstance(value, tuple) and not mixed
                else ()
            )
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

    def retranslate_ui(self) -> None:
        self._field_label.setText(
            QCoreApplication.translate("MetadataFields", self.spec.label)
        )
        self.reset_button.setText(self.tr("Reset"))
        editor = self.editor
        if isinstance(editor, AppComboBox):
            advisory_labels = {
                ContentAdvisory.UNSPECIFIED: self.tr("Unspecified"),
                ContentAdvisory.EXPLICIT: self.tr("Explicit"),
                ContentAdvisory.CLEAN: self.tr("Clean"),
            }
            for index in range(editor.count()):
                value = editor.itemData(index)
                if value is None:
                    if self.mixed:
                        label = QCoreApplication.translate(
                            "EditorLabels", "Mixed values"
                        )
                    else:
                        retained = (
                            " + ".join(
                                self.tr(_MEDIA_TYPE_LABELS.get(kind, kind.value))
                                for kind in self.initial
                                if isinstance(kind, MediaType)
                            )
                            if isinstance(self.initial, tuple)
                            else str(self.initial)
                        )
                        label = self.tr("Current (%1)").replace("%1", retained)
                elif self.spec.kind is FieldKind.BOOLEAN:
                    label = self.tr("Yes") if value else self.tr("No")
                elif self.spec.kind is FieldKind.ADVISORY:
                    label = advisory_labels[ContentAdvisory(value)]
                else:
                    label = self.tr(_MEDIA_TYPE_LABELS[MediaType(value)])
                editor.setItemText(index, label)
            if self.spec.kind is FieldKind.MEDIA_TYPE:
                editor.setToolTip(
                    self.tr(
                        "Changes Library classification; keeps the existing media file."
                    )
                    if self._media_type_choices
                    else self.tr(
                        "Select audio Tracks or video Tracks with a known media type "
                        "to change their classification together."
                    )
                )
        elif isinstance(editor, QLineEdit | QPlainTextEdit):
            editor.setPlaceholderText(
                self.tr("Mixed values — unchanged")
                if self.mixed
                else self.tr("ISO date or Unix seconds; blank to clear")
                if self.spec.kind is FieldKind.DATE
                else ""
            )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _modified(self, *_args: object) -> None:
        if self._syncing:
            return
        if (
            (self.mixed or self.spec.kind is FieldKind.MEDIA_TYPE)
            and isinstance(self.editor, AppComboBox)
            and self.editor.currentData() is None
        ):
            self._set_modified(False)
            return
        self._set_modified(True)

    def is_modified(self) -> bool:
        return self._modified_state

    def adopt_loaded_text(self, text: str) -> None:
        """Show a lazily read value without treating it as a user edit."""
        if self.is_modified() or not isinstance(self.editor, QPlainTextEdit):
            return
        self.initial = text
        self._syncing = True
        try:
            self.editor.setPlainText(text)
        finally:
            self._syncing = False

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
                initial: object = self.initial
                if self.spec.kind is FieldKind.MEDIA_TYPE:
                    initial = (
                        self.initial[0]
                        if isinstance(self.initial, tuple) and len(self.initial) == 1
                        else None
                    )
                index = editor.findData(initial)
                editor.setCurrentIndex(0 if self.mixed or index < 0 else index)
            elif isinstance(editor, ChapterEditor):
                editor.set_chapters(
                    tuple(
                        chapter
                        for chapter in self.initial
                        if isinstance(chapter, TrackChapter)
                    )
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
            if self.spec.kind is FieldKind.MEDIA_TYPE and isinstance(value, str):
                return MediaType(value)
            if isinstance(value, bool | ContentAdvisory):
                return value
            raise ValueError(self.tr("Choose a value to replace mixed values."))
        raise ValueError(self.tr("This field cannot be edited."))


__all__ = ["ChapterEditor", "FieldEditor"]
