"""Photo metadata editing over one revision-bound Library Draft."""

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace, PhotoUpdate
from iOpenPod.app.metadata_fields import FieldKind, MetadataField
from iOpenPod.GUI.presentation.i18n.text import (
    changed_field_count_text,
    english_count_fallback,
)
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.widgets.metadata_field_editor import FieldEditor
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

_PHOTO_FIELDS = (
    MetadataField(
        "rating",
        str(QT_TRANSLATE_NOOP("MetadataFields", "Rating (0-100)")),
        "Photo",
        FieldKind.INTEGER,
    ),
    MetadataField(
        "original_date",
        str(QT_TRANSLATE_NOOP("MetadataFields", "Original date")),
        "Dates",
        FieldKind.DATE,
    ),
    MetadataField(
        "taken_date",
        str(QT_TRANSLATE_NOOP("MetadataFields", "Taken date")),
        "Dates",
        FieldKind.DATE,
    ),
)


class PhotoMetadataEditorDialog(QDialog):
    """Apply supported metadata to one or more Photos as one atomic draft edit."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        photo_ids: tuple[int, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photoMetadataEditor")
        self.setModal(True)
        self._workspace = workspace
        self._revision = workspace.edit_revision
        self._photos = tuple(
            photo
            for photo_id in dict.fromkeys(photo_ids)
            if (photo := workspace.photo(photo_id)) is not None
        )
        if not self._photos or len(self._photos) != len(set(photo_ids)):
            raise ValueError("Select Photos from the current Library.")

        count = len(self._photos)
        self.setWindowTitle(
            self.tr("Edit Photo")
            if count == 1
            else english_count_fallback(
                "Edit %n Photo(s)", self.tr("Edit %n Photo(s)", "", count), count
            )
        )
        self.resize(820, 620)
        self.setMinimumSize(700, 520)
        self.rows: dict[str, FieldEditor] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        outer.addWidget(self._header())

        self._nav = QListWidget(self)
        self._nav.setObjectName("metadataSectionNav")
        self._nav.setFixedWidth(178)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pages = QStackedWidget(self)
        self._pages.setObjectName("metadataEditorPages")
        self._add_metadata_page()
        self._add_technical_page()
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        content.addWidget(self._nav)
        content.addWidget(self._pages, 1)
        outer.addLayout(content, 1)

        self._error = QLabel(self)
        self._error.setObjectName("metadataEditError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        outer.addWidget(self._error)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self._change_label = QLabel(
            QCoreApplication.translate("EditorLabels", "No changes"), self
        )
        self._change_label.setObjectName("metadataChangeSummary")
        footer.addWidget(self._change_label)
        self._reset_button = ActionButton(
            QCoreApplication.translate("CommonActions", "Reset Changes"), self
        )
        self._reset_button.setObjectName("resetPhotoMetadataChanges")
        self._reset_button.setEnabled(False)
        self._reset_button.clicked.connect(self._reset)
        footer.addWidget(self._reset_button)
        footer.addStretch(1)
        cancel = ActionButton(
            QCoreApplication.translate("CommonActions", "Cancel"), self
        )
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply_button = ActionButton(
            QCoreApplication.translate("CommonActions", "Apply"),
            self,
            kind=ActionButtonKind.PRIMARY,
        )
        apply_button.setObjectName("applyPhotoMetadataChanges")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        footer.addWidget(apply_button)
        outer.addLayout(footer)

    def _header(self) -> QFrame:
        header = QFrame(self)
        header.setObjectName("metadataEditorHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        title = QLabel(self.windowTitle(), header)
        title.setObjectName("metadataEditorTitle")
        layout.addWidget(title)
        subtitle = QLabel(self._selection_summary(), header)
        subtitle.setObjectName("metadataEditorSubtitle")
        layout.addWidget(subtitle)
        return header

    def _add_metadata_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("metadataEditorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(
            self._page_header(
                self.tr("Photo metadata"),
                self.tr("Rating and dates stored in the Photo Library"),
            )
        )

        values_by_path = {
            spec.path: tuple(getattr(photo, spec.path) for photo in self._photos)
            for spec in _PHOTO_FIELDS
        }
        for spec in _PHOTO_FIELDS:
            values = values_by_path[spec.path]
            row = FieldEditor(
                spec,
                values[0],
                any(value != values[0] for value in values[1:]),
                page,
            )
            row.modifiedChanged.connect(self._update_change_summary)
            self.rows[spec.path] = row

        layout.addWidget(self._section_panel(self.tr("Rating"), (self.rows["rating"],)))
        layout.addWidget(
            self._section_panel(
                self.tr("Dates"),
                (self.rows["original_date"], self.rows["taken_date"]),
            )
        )
        note = QLabel(
            self.tr(
                "Dates accept an ISO timestamp or Unix seconds. Leave a date blank "
                "to clear it; enter 0 to clear mixed dates."
            ),
            page,
        )
        note.setObjectName("metadataGroupDescription")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._pages.addWidget(page)
        self._nav.addItem(QListWidgetItem(self.tr("Metadata")))

    def _add_technical_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("metadataEditorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(
            self._page_header(
                QCoreApplication.translate("EditorLabels", "Technical details"),
                self.tr("Read-only source and representation facts"),
            )
        )
        technical = QTreeWidget(page)
        technical.setObjectName("metadataTechnicalDetails")
        technical.setHeaderLabels(
            [
                QCoreApplication.translate("EditorLabels", "Read-only field"),
                self.tr("Value"),
            ]
        )
        for label, values in (
            (self.tr("Photo ID"), tuple(photo.photo_id for photo in self._photos)),
            (
                self.tr("Source size (bytes)"),
                tuple(photo.source_size_bytes for photo in self._photos),
            ),
            (
                self.tr("Stored representations"),
                tuple(len(photo.representations) for photo in self._photos),
            ),
        ):
            technical.addTopLevelItem(
                QTreeWidgetItem([label, self._common_value(values)])
            )
        technical.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(technical, 1)
        self._pages.addWidget(page)
        self._nav.addItem(
            QListWidgetItem(
                QCoreApplication.translate("EditorLabels", "Technical details")
            )
        )

    def _page_header(self, title_text: str, description_text: str) -> QFrame:
        header = QFrame(self)
        header.setObjectName("metadataPageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        title = QLabel(title_text, header)
        title.setObjectName("metadataGroupTitle")
        layout.addWidget(title)
        description = QLabel(description_text, header)
        description.setObjectName("metadataGroupDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        return header

    def _section_panel(
        self,
        title_text: str,
        rows: tuple[FieldEditor, ...],
    ) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("metadataSectionPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        title = QLabel(title_text, panel)
        title.setObjectName("metadataSectionTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, row in enumerate(rows):
            grid.addWidget(row, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return panel

    def _selection_summary(self) -> str:
        if len(self._photos) == 1:
            return QCoreApplication.translate("LibraryLabels", "Photo %1").replace(
                "%1", str(self._photos[0].photo_id)
            )
        return english_count_fallback(
            "%n selected Photo(s)",
            self.tr("%n selected Photo(s)", "", len(self._photos)),
            len(self._photos),
        )

    def _reset(self) -> None:
        for row in self.rows.values():
            row.reset()
        self._error.clear()
        self._update_change_summary()

    def _update_change_summary(self) -> None:
        count = sum(row.is_modified() for row in self.rows.values())
        self._change_label.setText(
            QCoreApplication.translate("EditorLabels", "No changes")
            if count == 0
            else changed_field_count_text(count)
        )
        self._reset_button.setEnabled(count > 0)

    def accept(self) -> None:
        values: dict[str, int] = {}
        errors: list[str] = []
        for spec in _PHOTO_FIELDS:
            row = self.rows[spec.path]
            if not row.is_modified():
                continue
            try:
                value = row.value()
                if type(value) is not int:
                    raise ValueError(self.tr("Use a whole number."))
                if spec.path == "rating" and not 0 <= value <= 100:
                    raise ValueError(self.tr("Use a rating from 0 to 100."))
                if spec.kind is FieldKind.DATE and not 0 <= value <= 0xFFFFFFFF:
                    raise ValueError(
                        self.tr("Use a date supported by this Photo Database.")
                    )
                values[spec.path] = value
            except (ValueError, OverflowError, OSError) as error:
                label = QCoreApplication.translate("MetadataFields", spec.label)
                errors.append(f"{label}: {workflow_text(str(error))}")
        if errors:
            self._error.setText("\n".join(errors))
            return

        try:
            self._workspace.apply_photo_edits(
                tuple(
                    PhotoUpdate(
                        photo.photo_id,
                        rating=values.get("rating"),
                        original_date=values.get("original_date"),
                        taken_date=values.get("taken_date"),
                    )
                    for photo in self._photos
                ),
                self._revision,
            )
        except ValueError as error:
            self._error.setText(workflow_text(str(error)))
            return
        super().accept()

    def _common_value(self, values: tuple[int, ...]) -> str:
        return (
            str(values[0])
            if all(value == values[0] for value in values[1:])
            else QCoreApplication.translate("EditorLabels", "Mixed values")
        )


__all__ = ["PhotoMetadataEditorDialog"]
