"""Review playlist files that sit outside the selected Host scan scope."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import PlaylistExternalReference
    from storage import HostPath

_INVALID_INDEX = QModelIndex()
type _ModelIndex = QModelIndex | QPersistentModelIndex


class _ExternalPlaylistFilesModel(QAbstractTableModel):
    """Virtualized, checkable projection of out-of-scope playlist entries."""

    def __init__(
        self,
        references: tuple[PlaylistExternalReference, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._references = references
        self._accepted: set[int] = set()

    def rowCount(self, parent: _ModelIndex = _INVALID_INDEX) -> int:
        return len(self._references)

    def columnCount(self, parent: _ModelIndex = _INVALID_INDEX) -> int:
        return 4

    def data(
        self, index: _ModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._references):
            return None
        reference = self._references[index.row()]
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return (
                Qt.CheckState.Checked
                if index.row() in self._accepted
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return ""
            if index.column() == 1:
                return os.fspath(reference.target)
            if index.column() == 2:
                return ", ".join(playlist.path.name for playlist in reference.playlists)
            if index.column() == 3:
                return (
                    self.tr("Available")
                    if reference.available
                    else reference.detail or self.tr("Unavailable")
                )
        if role == Qt.ItemDataRole.ToolTipRole:
            if not reference.available:
                return reference.detail or self.tr(
                    "This file is currently unavailable and cannot be scanned."
                )
            playlists = "\n".join(os.fspath(path) for path in reference.playlists)
            return os.fspath(reference.target) + "\n\n" + playlists
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self.tr("Accept scanning %1").replace(
                "%1", os.fspath(reference.target)
            )
        return None

    def setData(
        self,
        index: _ModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or not index.isValid()
            or index.column() != 0
            or not self._references[index.row()].available
        ):
            return False
        if cast("Qt.CheckState", value) == Qt.CheckState.Checked:
            self._accepted.add(index.row())
        else:
            self._accepted.discard(index.row())
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def flags(self, index: _ModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if not index.isValid():
            return flags
        if not self._references[index.row()].available:
            return flags & ~Qt.ItemFlag.ItemIsEnabled
        if index.column() == 0:
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation != Qt.Orientation.Horizontal
            or role != Qt.ItemDataRole.DisplayRole
        ):
            return None
        return (
            self.tr("Scan"),
            self.tr("File"),
            self.tr("Referenced by"),
            self.tr("Status"),
        )[section]

    @property
    def accepted_paths(self) -> frozenset[HostPath]:
        return frozenset(
            reference.target
            for row, reference in enumerate(self._references)
            if row in self._accepted and reference.available
        )

    def set_all(self, accepted: bool) -> None:
        self._accepted = (
            {
                row
                for row, reference in enumerate(self._references)
                if reference.available
            }
            if accepted
            else set()
        )
        if self._references:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._references) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )


class ExternalPlaylistFilesDialog(QDialog):
    """Let the user explicitly extend one scan beyond the chosen folders."""

    def __init__(
        self,
        references: tuple[PlaylistExternalReference, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("externalPlaylistFilesDialog")
        self.setModal(True)
        self.resize(780, 480)
        self.setMinimumSize(620, 380)

        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        self._model = _ExternalPlaylistFilesModel(references, self)
        self._table = QTableView(self)
        self._table.setObjectName("externalPlaylistFilesTable")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(LAYOUT.control_height)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self._accept_all = ActionButton(
            parent=self,
            kind=ActionButtonKind.SECONDARY,
        )
        self._accept_all.setObjectName("acceptAllPlaylistFiles")
        self._deny_all = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._deny_all.setObjectName("denyAllPlaylistFiles")
        bulk = QHBoxLayout()
        bulk.setContentsMargins(0, 0, 0, 0)
        bulk.setSpacing(LAYOUT.space_xs)
        bulk.addStretch(1)
        bulk.addWidget(self._deny_all)
        bulk.addWidget(self._accept_all)

        self._buttons = QDialogButtonBox(self)
        self._cancel = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._continue = self._buttons.addButton(
            "",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._continue.setObjectName("continueMediaScan")
        apply_action_button_kind(self._cancel, ActionButtonKind.SECONDARY)
        apply_action_button_kind(self._continue, ActionButtonKind.PRIMARY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addLayout(bulk)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._buttons)

        self._accept_all.clicked.connect(lambda: self._model.set_all(True))
        self._deny_all.clicked.connect(lambda: self._model.set_all(False))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self.retranslate_ui()

    @property
    def accepted_paths(self) -> frozenset[HostPath]:
        return self._model.accepted_paths

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Playlist Files Outside Media Selection"))
        self._title.setText(self.tr("Choose external playlist files"))
        self._description.setText(
            self.tr(
                "These playlists reference files outside your current media selection, "
                "including excluded file types and subfolders. Choose which audio and "
                "video files this scan may read. Nothing is selected by default. "
                "Unchecked files stay out of the Host Media Library; approval applies "
                "only to this scan."
            )
        )
        self._accept_all.setText(self.tr("Accept All"))
        self._deny_all.setText(self.tr("Deny All"))
        self._cancel.setText(self.tr("Cancel Scan"))
        self._continue.setText(self.tr("Finish Scan"))


__all__ = ["ExternalPlaylistFilesDialog"]
