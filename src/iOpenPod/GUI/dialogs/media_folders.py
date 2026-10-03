"""Choose the user-owned folders that make up the Host Media Library."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.host_media_folders import (
    ALL_HOST_MEDIA_TYPES,
    HostMediaFolder,
    HostMediaType,
    create_host_media_folder,
    load_host_media_folders,
    same_host_media_folder,
    save_host_media_folders,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
    apply_action_button_kind,
)

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService


class _MediaFolderRow(QFrame):
    """Present one folder and stage its scan settings."""

    changed = Signal(object)
    removeRequested = Signal(object)

    def __init__(
        self,
        folder: HostMediaFolder,
        index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mediaFolderRow")
        self._folder = folder

        self._number = QLabel(self)
        self._number.setObjectName("mediaFolderNumber")
        self._number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._number.setFixedSize(
            LAYOUT.control_height_compact,
            LAYOUT.control_height_compact,
        )

        self._path = QLabel(os.fspath(folder.path), self)
        self._path.setObjectName("mediaFolderPath")
        self._path.setTextFormat(Qt.TextFormat.PlainText)
        self._path.setWordWrap(True)
        self._path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._settings_button = IconButton(
            "settings-sliders",
            "",
            self,
            checkable=True,
            kind=IconButtonKind.SUBTLE,
        )
        self._settings_button.setObjectName("mediaFolderSettingsButton")
        self._remove_button = IconButton(
            "x",
            "",
            self,
            kind=IconButtonKind.DANGER,
        )
        self._remove_button.setObjectName("removeMediaFolder")

        summary = QHBoxLayout()
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(LAYOUT.space_xs)
        summary.addWidget(self._number, 0)
        summary.addWidget(self._path, 1)
        summary.addWidget(self._settings_button, 0)
        summary.addWidget(self._remove_button, 0)

        self._settings_panel = QFrame(self)
        self._settings_panel.setObjectName("mediaFolderSettings")
        settings_layout = QVBoxLayout(self._settings_panel)
        settings_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        settings_layout.setSpacing(LAYOUT.space_xs)

        self._recurse = QCheckBox(self._settings_panel)
        self._recurse.setObjectName("recurseMediaFolder")
        self._recurse.setChecked(folder.recurse)
        settings_layout.addWidget(self._recurse)

        self._scan_label = QLabel(self._settings_panel)
        self._scan_label.setObjectName("mediaFolderScanLabel")
        settings_layout.addWidget(self._scan_label)

        media_layout = QHBoxLayout()
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(LAYOUT.space_md)
        self._media_checkboxes: dict[HostMediaType, QCheckBox] = {}
        for media_type in ALL_HOST_MEDIA_TYPES:
            checkbox = QCheckBox(self._settings_panel)
            checkbox.setObjectName(f"scan{media_type.value.title()}")
            checkbox.setProperty("mediaType", media_type.value)
            checkbox.setChecked(media_type in folder.media_types)
            checkbox.toggled.connect(self._settings_changed)
            self._media_checkboxes[media_type] = checkbox
            media_layout.addWidget(checkbox)
        media_layout.addStretch(1)
        settings_layout.addLayout(media_layout)
        self._settings_panel.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_xs,
            LAYOUT.space_sm,
            LAYOUT.space_xs,
        )
        layout.setSpacing(LAYOUT.space_2xs)
        layout.addLayout(summary)
        layout.addWidget(self._settings_panel)

        self._settings_button.toggled.connect(self._set_expanded)
        self._remove_button.clicked.connect(self._remove_requested)
        self._recurse.toggled.connect(self._settings_changed)
        self.set_index(index)
        self.retranslate_ui()

    @property
    def folder(self) -> HostMediaFolder:
        return self._folder

    def set_index(self, index: int) -> None:
        self._number.setText(str(index))

    def show_settings_only(self) -> None:
        """Present the folder's expanded settings without list editing actions."""

        self._number.hide()
        self._settings_button.hide()
        self._remove_button.hide()
        self._set_expanded(True)

    def retranslate_ui(self) -> None:
        self._settings_button.setAccessibleName(self.tr("Folder settings"))
        self._settings_button.setToolTip(self.tr("Folder settings"))
        self._remove_button.setAccessibleName(self.tr("Remove folder"))
        self._remove_button.setToolTip(self.tr("Remove folder"))
        self._recurse.setText(self.tr("Recurse into subfolders"))
        self._scan_label.setText(self.tr("Scan for"))
        labels = {
            HostMediaType.AUDIO: self.tr("Audio"),
            HostMediaType.VIDEO: self.tr("Video"),
            HostMediaType.PHOTOS: self.tr("Photos"),
            HostMediaType.PLAYLISTS: self.tr("Playlists"),
        }
        for media_type, checkbox in self._media_checkboxes.items():
            checkbox.setText(labels[media_type])

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _set_expanded(self, expanded: bool) -> None:
        self._settings_panel.setVisible(expanded)
        self._settings_button.setProperty("expanded", expanded)

    def _settings_changed(self, _checked: bool) -> None:
        self._folder = HostMediaFolder(
            path=self._folder.path,
            recurse=self._recurse.isChecked(),
            media_types=frozenset(
                media_type
                for media_type, checkbox in self._media_checkboxes.items()
                if checkbox.isChecked()
            ),
        )
        self.changed.emit(self._folder)

    def _remove_requested(self) -> None:
        self.removeRequested.emit(self)


class MediaFolderSettingsDialog(QDialog):
    """Choose a dropped folder's temporary scan settings before starting Sync."""

    def __init__(self, folder: HostMediaFolder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mediaFolderSettingsDialog")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._row = _MediaFolderRow(folder, 1, self)
        self._row.show_settings_only()
        self._buttons = QDialogButtonBox(self)
        self._cancel = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._sync = self._buttons.addButton("", QDialogButtonBox.ButtonRole.AcceptRole)
        self._sync.setObjectName("syncDroppedMediaFolder")
        self._sync.setDefault(True)
        apply_action_button_kind(self._cancel, ActionButtonKind.SECONDARY)
        apply_action_button_kind(self._sync, ActionButtonKind.PRIMARY)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._row)
        layout.addWidget(self._buttons)
        self.retranslate_ui()

    @property
    def folder(self) -> HostMediaFolder:
        return self._row.folder

    def retranslate_ui(self) -> None:
        self.setWindowTitle(
            QCoreApplication.translate("_MediaFolderRow", "Folder settings")
        )
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._sync.setText(QCoreApplication.translate("MediaFoldersDialog", "Sync"))
        self._row.retranslate_ui()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class MediaFoldersDialog(QDialog):
    """Stage Host Media Library folder choices and persist them on Sync."""

    def __init__(
        self,
        settings: SettingsService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mediaFoldersDialog")
        self.setModal(True)
        self.resize(680, 560)
        self.setMinimumSize(560, 460)
        self._settings = settings
        self._rows: list[_MediaFolderRow] = []

        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        self._summary = QLabel(self)
        self._summary.setObjectName("mediaFolderSummary")
        self._add = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        self._add.setObjectName("addMediaFolder")
        self._clear = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._clear.setObjectName("clearMediaFolders")

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(LAYOUT.space_xs)
        actions.addWidget(self._summary, 1)
        actions.addWidget(self._clear)
        actions.addWidget(self._add)

        self._folder_list = QFrame(self)
        self._folder_list.setObjectName("mediaFoldersList")
        self._folder_layout = QVBoxLayout(self._folder_list)
        self._folder_layout.setContentsMargins(0, 0, 0, 0)
        self._folder_layout.setSpacing(0)

        self._empty = QLabel(self._folder_list)
        self._empty.setObjectName("mediaFolderEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._folder_layout.addWidget(self._empty, 1)
        self._folder_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setObjectName("mediaFoldersScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._folder_list)

        self._buttons = QDialogButtonBox(self)
        self._cancel = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._sync = self._buttons.addButton(
            "",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._sync.setObjectName("syncMediaFolders")
        apply_action_button_kind(self._cancel, ActionButtonKind.SECONDARY)
        apply_action_button_kind(self._sync, ActionButtonKind.PRIMARY)

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
        layout.addLayout(actions)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._buttons)

        self._add.clicked.connect(self._choose_folder)
        self._clear.clicked.connect(self.clear_folders)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        for folder in load_host_media_folders(settings):
            self.add_folder(folder)
        self.retranslate_ui()
        self._refresh_summary()

    @property
    def folders(self) -> tuple[HostMediaFolder, ...]:
        return tuple(row.folder for row in self._rows)

    def add_folder(self, value: HostMediaFolder | str | os.PathLike[str]) -> bool:
        """Add one staged folder, returning false when it is already present."""

        folder = (
            value
            if isinstance(value, HostMediaFolder)
            else create_host_media_folder(value)
        )
        if any(same_host_media_folder(folder, row.folder) for row in self._rows):
            return False
        row = _MediaFolderRow(folder, len(self._rows) + 1, self._folder_list)
        row.changed.connect(self._folder_changed)
        row.removeRequested.connect(self._remove_row)
        self._folder_layout.insertWidget(len(self._rows), row)
        self._rows.append(row)
        self._refresh_summary()
        return True

    def clear_folders(self) -> None:
        """Remove every staged folder without changing persisted settings yet."""

        for row in self._rows:
            self._folder_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._refresh_summary()

    def accept(self) -> None:
        save_host_media_folders(self._settings, self.folders)
        super().accept()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Choose Media Folders"))
        self._title.setText(self.tr("Choose Media Folders"))
        self._description.setText(
            self.tr(
                "Choose the folders that make up your Host Media Library. "
                "Each folder can scan subfolders and selected media types."
            )
        )
        self._add.setText(self.tr("Add Folder…"))
        self._clear.setText(self.tr("Clear"))
        self._empty.setText(
            self.tr("No media folders selected. Add a folder to get started.")
        )
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._sync.setText(self.tr("Sync"))
        for row in self._rows:
            row.retranslate_ui()
        self._refresh_summary()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _choose_folder(self) -> None:
        start = (
            Path(os.fspath(self._rows[-1].folder.path)) if self._rows else Path.home()
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            self.tr("Add Media Folder"),
            os.fspath(start),
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected:
            self.add_folder(selected)

    def _remove_row(self, value: object) -> None:
        if not isinstance(value, _MediaFolderRow) or value not in self._rows:
            return
        self._rows.remove(value)
        self._folder_layout.removeWidget(value)
        value.deleteLater()
        for index, row in enumerate(self._rows, start=1):
            row.set_index(index)
        self._refresh_summary()

    def _folder_changed(self, _folder: object) -> None:
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        count = len(self._rows)
        self._summary.setText(
            self.tr("%n folder selected", None, count)
            if count == 1
            else self.tr("%n folders selected", None, count)
        )
        self._clear.setEnabled(count > 0)
        self._empty.setVisible(count == 0)


__all__ = ["MediaFolderSettingsDialog", "MediaFoldersDialog"]
