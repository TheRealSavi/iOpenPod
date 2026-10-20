"""Individual Playlist choices using the existing desktop theme and Qt navigation.

Hallmark · component: Playlist Review · genre: modern-minimal · theme: iOpenPod
States inherit native selection/focus and themed buttons; blocked reasons are text.
Pre-emit critique: P5 H4 E4 S5 R5 V4. No added motion; native keyboard navigation.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.playlist_sync import (
    PlaylistSyncChoice,
    PlaylistSyncReviewItem,
    playlist_sync_target,
)
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import LibrarySnapshot

_ROOT = QModelIndex()
type _Index = QModelIndex | QPersistentModelIndex


class PlaylistSyncTableModel(QAbstractTableModel):
    choiceChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: tuple[PlaylistSyncReviewItem, ...] = ()

    def replace_rows(self, rows: tuple[PlaylistSyncReviewItem, ...]) -> None:
        if self.rows == rows:
            return
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: _Index = _ROOT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: _Index = _ROOT) -> int:
        return 0 if parent.isValid() else 3

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return (self.tr("Host Playlist"), self.tr("On iPod"), self.tr("Changes"))[
                section
            ]
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(
        self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole.value
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return (
                Qt.CheckState.Checked
                if row.choice.included
                else Qt.CheckState.Unchecked
            )
        values = (
            row.name,
            row.target_name
            or (
                self.tr("Choose a match…")
                if row.issue_code == "sync.playlist_ambiguous"
                else self.tr("Create new Playlist")
            ),
            self.describe(row),
        )
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return values[index.column()]
        if role in (
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleDescriptionRole,
        ):
            return "\n".join(
                filter(
                    None,
                    (
                        *values,
                        workflow_text(row.match_detail),
                        workflow_text(row.detail),
                        row.source_path,
                    ),
                )
            )
        return None

    def setData(
        self, index: _Index, value: object, role: int = Qt.ItemDataRole.EditRole.value
    ) -> bool:
        if (
            not index.isValid()
            or index.column() != 0
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        row = self.rows[index.row()]
        included = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        choice = replace(row.choice, included=included)
        rows = list(self.rows)
        rows[index.row()] = replace(row, choice=choice)
        self.rows = tuple(rows)
        self.dataChanged.emit(index, self.index(index.row(), 2))
        self.choiceChanged.emit(choice)
        return True

    def describe(self, row: PlaylistSyncReviewItem) -> str:
        if not row.choice.included:
            return self.tr("Skipped")
        if row.issue_code:
            return self.tr("Needs attention")
        if row.change is None:
            return (
                self.tr("Save match")
                if row.needs_association
                else self.tr("Up to date")
            )
        change = row.change
        parts: list[str] = []
        if change.action == "create":
            parts.append(self.tr("Create"))
        if change.renamed:
            parts.append(self.tr("Rename"))
        if change.added_count or change.removed_count:
            parts.append(
                self.tr("%1 added, %2 removed")
                .replace("%1", str(change.added_count))
                .replace("%2", str(change.removed_count))
            )
        if change.order_changed:
            parts.append(self.tr("Reorder"))
        return " · ".join(parts)


class PlaylistMatchDialog(QDialog):
    """Choose a regular target, with source and contents available for disambiguation."""

    def __init__(
        self, row: PlaylistSyncReviewItem, library: LibrarySnapshot, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playlistMatchDialog")
        self.setWindowTitle(self.tr("Choose Playlist match"))
        self.resize(560, 480)
        self.target_id: int | None = row.target_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([LAYOUT.space_lg] * 4))
        layout.setSpacing(LAYOUT.space_sm)
        heading = QLabel(row.name, self)
        heading.setObjectName("dialogTitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if row.source_path:
            source = QLineEdit(row.source_path, self)
            source.setReadOnly(True)
            source.setAccessibleName(self.tr("Host Playlist source"))
            source.setToolTip(row.source_path)
            source.setCursorPosition(0)
            layout.addWidget(source)
        explanation = QLabel(
            self.tr(
                "Use an existing iPod Playlist or create a new one. Sync will use the name, entries and order from the Host Playlist."
            ),
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        search = QLineEdit(self)
        search.setObjectName("playlistMatchSearch")
        search.setPlaceholderText(self.tr("Search iPod Playlists"))
        search.setAccessibleName(self.tr("Search iPod Playlists"))
        search_label = QLabel(self.tr("iPod Playlists"), self)
        search_label.setBuddy(search)
        layout.addWidget(search_label)
        layout.addWidget(search)
        self.targets = QListWidget(self)
        self.targets.setObjectName("playlistSyncTargets")
        self.targets.setUniformItemSizes(True)
        self.targets.setAccessibleName(self.tr("iPod Playlist matches"))
        new = QListWidgetItem(self.tr("Create new Playlist"), self.targets)
        new.setData(Qt.ItemDataRole.UserRole, None)
        selected = new
        playlists = {
            item.playlist_id: item
            for item in library.playlists
            if playlist_sync_target(item)
        }
        tracks = {item.track_id: item for item in library.tracks}
        for playlist in sorted(
            playlists.values(), key=lambda item: item.name.casefold()
        ):
            item = QListWidgetItem(
                self.tr("%1 · %2 Tracks")
                .replace("%1", playlist.name)
                .replace("%2", str(len(playlist.entries))),
                self.targets,
            )
            item.setData(Qt.ItemDataRole.UserRole, playlist.playlist_id)
            if playlist.playlist_id == row.target_id:
                selected = item
        layout.addWidget(self.targets, 1)
        detail = QLabel(self)
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        detail.setMinimumHeight(LAYOUT.control_height_large)
        layout.addWidget(detail)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = ActionButton(
            QCoreApplication.translate("CommonActions", "Cancel"), self
        )
        use = ActionButton(
            self.tr("Use this match"), self, kind=ActionButtonKind.PRIMARY
        )
        use.setDefault(True)
        actions.addWidget(cancel)
        actions.addWidget(use)
        layout.addLayout(actions)

        def describe() -> None:
            current = self.targets.currentRow()
            item = self.targets.item(current) if current >= 0 else None
            use.setEnabled(item is not None and not item.isHidden())
            identity = None if item is None else item.data(Qt.ItemDataRole.UserRole)
            self.target_id = identity if isinstance(identity, int) else None
            playlist = playlists.get(identity) if isinstance(identity, int) else None
            titles = (
                []
                if playlist is None
                else [
                    tracks[entry.track_id].title
                    for entry in playlist.entries[:6]
                    if entry.track_id in tracks
                ]
            )
            detail.setText(
                self.tr("A new Playlist will be added to the iPod.")
                if playlist is None
                else " · ".join(titles) or self.tr("Empty Playlist")
            )

        def search_targets(text: str) -> None:
            for index in range(self.targets.count()):
                item = self.targets.item(index)
                item.setHidden(
                    index != 0 and text.casefold() not in item.text().casefold()
                )
            describe()

        search.textChanged.connect(search_targets)
        self.targets.currentItemChanged.connect(describe)
        self.targets.setCurrentItem(selected)
        use.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        search.setFocus()


class PlaylistSyncReview(QWidget):
    choicesChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._choices: dict[int, PlaylistSyncChoice] = {}
        self._library = LibrarySnapshot()
        self.model = PlaylistSyncTableModel(self)
        self.table = QTableView(self)
        self.table.setObjectName("syncPlaylistReviewChanges")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(LAYOUT.control_height_large)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setMinimumHeight(LAYOUT.control_height_large * 3)
        self.table.setMaximumHeight(LAYOUT.control_height_large * 5)
        self._detail = QLabel(self)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._change = ActionButton(parent=self)
        self._change.setObjectName("changePlaylistMatch")
        self._change.clicked.connect(self._choose_match)
        self._change.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self._detail, 1)
        actions.addWidget(self._change)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        self.table.selectionModel().currentChanged.connect(self._describe_selected)
        self.table.doubleClicked.connect(self._choose_match)
        self.model.choiceChanged.connect(self.set_choice)
        self.retranslate()

    @property
    def choices(self) -> tuple[PlaylistSyncChoice, ...]:
        return tuple(self._choices.values())

    def set_choice(self, choice: PlaylistSyncChoice) -> None:
        self._choices[choice.host_playlist_id] = choice
        self.set_rows(
            tuple(
                replace(row, choice=choice)
                if row.host_playlist_id == choice.host_playlist_id
                else row
                for row in self.model.rows
            ),
            self._library,
        )
        self.choicesChanged.emit()

    def reset(self) -> None:
        self._choices.clear()
        self.set_rows((), LibrarySnapshot())

    def set_rows(
        self, rows: tuple[PlaylistSyncReviewItem, ...], library: LibrarySnapshot
    ) -> None:
        current = self.table.currentIndex().row()
        identity = (
            self.model.rows[current].host_playlist_id
            if 0 <= current < len(self.model.rows)
            else None
        )
        self._library = library
        self.model.replace_rows(rows)
        self.setVisible(bool(rows))
        if rows:
            self.table.setFixedHeight(
                self.table.horizontalHeader().height()
                + min(4, len(rows)) * LAYOUT.control_height_large
                + 2 * self.table.frameWidth()
            )
            selected = next(
                (i for i, row in enumerate(rows) if row.host_playlist_id == identity), 0
            )
            self.table.setCurrentIndex(self.model.index(selected, 0))
        self._describe_selected()

    def _describe_selected(self) -> None:
        index = self.table.currentIndex().row()
        self._change.setEnabled(0 <= index < len(self.model.rows))
        if not 0 <= index < len(self.model.rows):
            self._detail.clear()
            return
        row = self.model.rows[index]
        self._detail.setText(
            workflow_text(row.detail or row.match_detail)
            if row.choice.included
            else self.tr("Skipped this Sync. Track selection is unchanged.")
        )
        self._detail.setToolTip(row.source_path)
        self._detail.setAccessibleDescription(row.source_path)

    def _choose_match(self) -> None:
        index = self.table.currentIndex().row()
        if not 0 <= index < len(self.model.rows):
            return
        row = self.model.rows[index]
        dialog = PlaylistMatchDialog(row, self._library, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_choice(
                PlaylistSyncChoice(row.host_playlist_id, True, False, dialog.target_id)
            )
        dialog.deleteLater()

    def retranslate(self) -> None:
        self._describe_selected()
        self.table.setAccessibleName(self.tr("Playlist Sync choices"))
        self.table.setAccessibleDescription(
            self.tr(
                "Check a Playlist to sync it. Select a row and choose Change match to use another iPod Playlist."
            )
        )
        self._change.setText(self.tr("Change match…"))
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 2)
        if self.model.rows:
            self.model.dataChanged.emit(
                self.model.index(0, 0), self.model.index(len(self.model.rows) - 1, 2)
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
