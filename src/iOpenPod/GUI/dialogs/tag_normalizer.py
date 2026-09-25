"""Virtualized, searchable preview of a background tag-normalization scan."""

from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.metadata_fields import field_value, metadata_fields
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import TagProfile, TagSuggestion
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

_ROOT = QModelIndex()


@dataclass(frozen=True, slots=True)
class _Row:
    path: str
    values: tuple[str, str, str, str]


class SuggestionModel(QAbstractTableModel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.rows: tuple[_Row, ...] = ()
        self._visible: tuple[_Row, ...] = ()
        self._widget = parent

    def set_rows(self, rows: tuple[_Row, ...]) -> None:
        self.rows = rows
        self.filter("", "")

    def filter(self, query: str, path: str) -> None:
        query = query.strip().casefold()
        self.beginResetModel()
        self._visible = tuple(
            row
            for row in self.rows
            if (not path or row.path == path)
            and query in " ".join(row.values).casefold()
        )
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else 4

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            index.isValid()
            and 0 <= index.row() < len(self._visible)
            and 0 <= index.column() < 4
        ):
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
                return self._visible[index.row()].values[index.column()]
            if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
                return self._widget.palette().color(QPalette.ColorRole.Link)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation is Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < 4
        ):
            return (
                self.tr("Track"),
                self.tr("Tag"),
                self.tr("Current value"),
                self.tr("Suggested value"),
            )[section]
        return None


class TagNormalizerDialog(QDialog):
    def __init__(
        self, controller: TagNormalizationController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tagNormalizer")
        self.setWindowTitle(self.tr("Normalize iPod Tags"))
        self.resize(1040, 720)
        self.setMinimumSize(760, 560)
        self.controller = controller
        self._profile = TagProfile()
        self._shown: TagSuggestion | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*([LAYOUT.space_lg] * 4))
        outer.setSpacing(LAYOUT.space_sm)
        heading = QLabel(self.tr("Normalize iPod Tags"), self)
        heading.setObjectName("pageTitle")
        outer.addWidget(heading)
        introduction = QLabel(
            self.tr(
                "A little tidying for your Library. Keep names, album grouping, "
                "and sorting consistent on your iPod."
            ),
            self,
        )
        introduction.setObjectName("pageDescription")
        introduction.setWordWrap(True)
        outer.addWidget(introduction)

        overview = QFrame(self)
        overview.setObjectName("normalizationOverview")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(*([LAYOUT.space_md] * 4))
        overview_layout.setSpacing(LAYOUT.space_2xs)
        self._summary = QLabel(self)
        self._summary.setObjectName("sectionTitle")
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        overview_layout.addWidget(self._summary)
        self._profile_label = QLabel(self)
        self._profile_label.setObjectName("pageDescription")
        self._profile_label.setTextFormat(Qt.TextFormat.PlainText)
        self._profile_label.setWordWrap(True)
        overview_layout.addWidget(self._profile_label)
        outer.addWidget(overview)
        self._warnings = QLabel(self)
        self._warnings.setObjectName("normalizationWarnings")
        self._warnings.setWordWrap(True)
        self._warnings.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self._warnings)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText(self.tr("Track, artist, album, or tag value…"))
        self._search.setAccessibleName(self.tr("Search suggested changes"))
        self._search.setClearButtonEnabled(True)
        self._fields = AppComboBox(self)
        self._fields.setAccessibleName(self.tr("Filter by tag"))
        self._fields.addItem(self.tr("All tags"), "")
        filters = QHBoxLayout()
        filters.setSpacing(LAYOUT.space_sm)
        for label_text, control, stretch in (
            (self.tr("Search changes"), self._search, 1),
            (self.tr("Tag"), self._fields, 0),
        ):
            group = QVBoxLayout()
            group.setSpacing(LAYOUT.space_2xs)
            label = QLabel(label_text, self)
            label.setBuddy(control)
            group.addWidget(label)
            group.addWidget(control)
            filters.addLayout(group, stretch)
        outer.addLayout(filters)
        self.model = SuggestionModel(self)
        self.table = QTableView(self)
        self.table.setObjectName("normalizationChanges")
        self.table.setAccessibleName(self.tr("Suggested tag changes"))
        self.table.setModel(self.model)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().hide()
        self._size_rows()
        self._content = QStackedWidget(self)
        self._content.setObjectName("normalizationContent")
        self._content.addWidget(self.table)
        self._empty = QFrame(self)
        self._empty.setObjectName("normalizationEmpty")
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(*([LAYOUT.space_lg] * 4))
        empty_layout.setSpacing(LAYOUT.space_sm)
        empty_layout.addStretch(1)
        self._state_icon = QLabel(self)
        self._state_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._state_icon)
        self._empty_title = QLabel(self)
        self._empty_title.setObjectName("sectionTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setWordWrap(True)
        empty_layout.addWidget(self._empty_title)
        self._empty_detail = QLabel(self)
        self._empty_detail.setObjectName("pageDescription")
        self._empty_detail.setTextFormat(Qt.TextFormat.PlainText)
        self._empty_detail.setWordWrap(True)
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_detail)
        self._progress = QProgressBar(self)
        self._progress.setAccessibleName(self.tr("Checking Library tags"))
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(LAYOUT.space_2xs)
        empty_layout.addWidget(self._progress)
        self._clear_filters = ActionButton(self.tr("Clear filters"), self)
        self._clear_filters.clicked.connect(self._reset_filters)
        empty_layout.addWidget(self._clear_filters, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self._content.addWidget(self._empty)
        outer.addWidget(self._content, 1)
        self._results = QLabel(self)
        self._results.setObjectName("pageMeta")
        self._results.setWordWrap(True)
        outer.addWidget(self._results)
        self._status = QLabel(self)
        self._status.setObjectName("normalizationStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        outer.addWidget(self._status)
        self._scan = ActionButton(self.tr("Scan again"), self)
        self._apply = ActionButton(
            self.tr("Apply"),
            self,
            kind=ActionButtonKind.PRIMARY,
        )
        self._apply.setObjectName("applyNormalization")
        self._apply.setEnabled(False)
        self._apply.setAutoDefault(False)
        self._scan.setAutoDefault(False)
        close = ActionButton(self.tr("Close"), self)
        close.setAutoDefault(False)
        self._clear_filters.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self._scan)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(self._apply)
        outer.addLayout(buttons)
        self._scan.clicked.connect(self._rescan)
        self._apply.clicked.connect(self._accept_changes)
        close.clicked.connect(self.reject)
        self._search.textChanged.connect(self._filter)
        self._fields.currentIndexChanged.connect(self._filter)
        controller.changed.connect(self._refresh)
        self._refresh()

    def start(self, profile: TagProfile) -> None:
        self._profile = profile
        self.show()
        self.raise_()
        self._reset_filters()
        try:
            self.controller.ensure_scan(profile)
        except ValueError as error:
            self._status.setText(str(error))
        self._refresh()

    def _rescan(self) -> None:
        try:
            self.controller.start(self._profile)
        except ValueError as error:
            self._status.setText(str(error))

    def _refresh(self) -> None:
        # A background badge refresh should not build a hidden table of field edits.
        if not self.isVisible():
            return
        controller = self.controller
        suggestion = controller.suggestion
        self._progress.setVisible(controller.scanning)
        self._scan.setEnabled(
            not controller.scanning
            and not controller.workspace.locked
            and controller.workspace.snapshot is not None
        )
        self._scan.setText(
            self.tr("Checking…") if controller.scanning else self.tr("Scan again")
        )
        self._apply.setEnabled(
            suggestion is not None
            and bool(suggestion.updates)
            and not controller.workspace.locked
        )
        self._status.setText(controller.message)
        self._status.setVisible(
            bool(controller.message) and suggestion is None and not controller.scanning
        )
        self._search.setEnabled(suggestion is not None and bool(suggestion.updates))
        self._fields.setEnabled(self._search.isEnabled())
        if controller.scanning:
            summary = self.tr("Checking your Library…")
        elif suggestion is not None and suggestion.updates:
            summary = (
                self.tr("%1 tag changes across %2 tracks")
                .replace("%1", f"{suggestion.field_count:,}")
                .replace("%2", f"{len(suggestion.updates):,}")
            )
        elif suggestion is not None:
            summary = self.tr("Your tags are in good shape")
        else:
            summary = self.tr("Consistent tags, easier browsing")
        self._summary.setText(summary)
        profile = suggestion.profile if suggestion is not None else self._profile
        self._profile_label.setText(
            self.tr("Tailored to %1").replace("%1", profile.label)
        )
        self._apply.setText(
            self.tr("Apply all %1 changes").replace("%1", f"{suggestion.field_count:,}")
            if suggestion is not None and suggestion.updates
            else self.tr("Apply")
        )
        self._warnings.setText(
            "" if suggestion is None else "\n".join(suggestion.warnings)
        )
        self._warnings.setVisible(bool(self._warnings.text()))
        if suggestion is not self._shown:
            self._shown = suggestion
            self._populate(suggestion)
        self._filter()

    def _populate(self, suggestion: TagSuggestion | None) -> None:
        controller = self.controller
        rows: list[_Row] = []
        labels = {f.path: f.label for f in metadata_fields()}
        tracks = {t.track_id: t for t in controller.tracks}
        if suggestion is not None:
            for update in suggestion.updates:
                track = tracks[update.track_id]
                rows.extend(
                    _Row(
                        edit.field,
                        (
                            f"{track.title or self.tr('Untitled track')}\n{track.artist} · {track.album}",
                            labels.get(edit.field, edit.field),
                            self._display_value(field_value(track, edit.field)),
                            self._display_value(edit.value),
                        ),
                    )
                    for edit in update.edits
                )
        self.model.set_rows(tuple(rows))
        selected = self._fields.currentData()
        self._fields.blockSignals(True)
        self._fields.clear()
        self._fields.addItem(self.tr("All tags"), "")
        for path in sorted({row.path for row in rows}):
            self._fields.addItem(labels.get(path, path), path)
        self._fields.setCurrentIndex(max(0, self._fields.findData(selected)))
        self._fields.blockSignals(False)

    def _display_value(self, value: object) -> str:
        if isinstance(value, bool):
            return self.tr("Yes") if value else self.tr("No")
        if value is None or value == "":
            return self.tr("Not set")
        if isinstance(value, str):
            return "“" + value.replace("\n", "↵").replace("\t", "⇥") + "”"
        return str(value)

    def _filter(self, *_args: object) -> None:
        value: object = self._fields.currentData()
        self.model.filter(self._search.text(), value if isinstance(value, str) else "")
        self._refresh_content()

    def _reset_filters(self) -> None:
        self._search.clear()
        self._fields.setCurrentIndex(0)

    def _refresh_content(self) -> None:
        controller = self.controller
        suggestion = controller.suggestion
        total = suggestion.field_count if suggestion is not None else 0
        visible = self.model.rowCount()
        self._results.setVisible(total > 0)
        self._results.setText(
            self.tr("Showing %1 of %2 changes. Applying includes all %2 changes.")
            .replace("%1", f"{visible:,}")
            .replace("%2", f"{total:,}")
        )
        self._content.setCurrentWidget(self.table if visible else self._empty)
        self._clear_filters.setVisible(total > 0 and visible == 0)
        if controller.scanning:
            title = self.tr("Finding the finishing touches")
            detail = self.tr(
                "Checking names, album grouping, and sort tags. You can keep browsing while we work."
            )
        elif total:
            title = self.tr("No matching changes")
            detail = self.tr(
                "Try another search or clear the filters to see every suggestion."
            )
        elif suggestion is not None:
            title = self.tr("All tidy")
            detail = self.tr("No tag changes are needed.")
        elif controller.workspace.locked:
            title = self.tr("Your Library is busy")
            detail = self.tr(
                "Wait for the current operation to finish before checking tags."
            )
        elif controller.workspace.snapshot is None:
            title = self.tr("Choose an iPod to get started")
            detail = self.tr("Load its Library to check for suggested tag changes.")
        elif controller.failed:
            title = self.tr("We couldn't check your tags")
            detail = self.tr("Try scanning again.")
        else:
            title = self.tr("Ready for a fresh look")
            detail = self.tr("Scan your Library to preview suggested tag changes.")
        self._empty_title.setText(title)
        self._empty_detail.setText(detail)
        self._state_icon.setPixmap(
            glyph_icon(
                "check-circle" if suggestion is not None and not total else "search",
                LAYOUT.space_xl,
                self.palette().color(QPalette.ColorRole.Link),
                self.devicePixelRatioF(),
            ).pixmap(LAYOUT.space_xl, LAYOUT.space_xl)
        )

    def _size_rows(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(
            max(
                LAYOUT.collection_list_row_height,
                self.table.fontMetrics().lineSpacing() * 2 + LAYOUT.space_md,
            )
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "_results") and event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }:
            self._size_rows()
            self._refresh_content()

    def _accept_changes(self) -> None:
        try:
            self.controller.apply()
        except ValueError as error:
            self._status.setText(str(error))

    def reject(self) -> None:
        # The shell owns a monitored scan; closing its preview does not stop the badge.
        if not self.controller.monitoring:
            self.controller.cancel()
        super().reject()
