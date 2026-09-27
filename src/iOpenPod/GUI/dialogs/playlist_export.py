"""Playlist export choices before the native Host folder picker opens."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_export import PlaylistExportMode, PlaylistFileType
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class PlaylistExportDialog(QDialog):
    """Choose the target paths and document format for one Playlist export."""

    def __init__(self, track_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("playlistExportDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(540)
        self._track_count = track_count

        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        self.device_references = QRadioButton(self)
        self.device_references.setObjectName("deviceReferenceExport")
        self.device_references.setProperty(
            "exportMode", PlaylistExportMode.DEVICE_REFERENCES.value
        )
        self.copy_tracks = QRadioButton(self)
        self.copy_tracks.setObjectName("copyTrackExport")
        self.copy_tracks.setProperty("exportMode", PlaylistExportMode.COPY_TRACKS.value)
        self.copy_tracks.setChecked(True)
        modes = QButtonGroup(self)
        modes.addButton(self.device_references)
        modes.addButton(self.copy_tracks)

        self.file_type = AppComboBox(self)
        self.file_type.setObjectName("playlistFileType")
        for value in PlaylistFileType:
            self.file_type.addItem(self._file_type_text(value), value.value)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(LAYOUT.space_sm)
        self._file_type_label = QLabel(self)
        self._file_type_label.setBuddy(self.file_type)
        form.addRow(self._file_type_label, self.file_type)

        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        self._continue = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._continue.setDefault(True)
        self._continue.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._continue)

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
        layout.addWidget(self.device_references)
        layout.addWidget(self.copy_tracks)
        layout.addLayout(form)
        layout.addLayout(actions)
        self.retranslate_ui()

    @property
    def mode(self) -> PlaylistExportMode:
        return (
            PlaylistExportMode.COPY_TRACKS
            if self.copy_tracks.isChecked()
            else PlaylistExportMode.DEVICE_REFERENCES
        )

    @property
    def selected_file_type(self) -> PlaylistFileType:
        return PlaylistFileType(str(self.file_type.currentData()))

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Export Playlist"))
        self._title.setText(self.tr("Export Playlist"))
        self.device_references.setAccessibleName(self.tr("Reference Tracks on iPod"))
        self.copy_tracks.setAccessibleName(self.tr("Copy Tracks"))
        self.file_type.setAccessibleName(self.tr("Playlist file type"))
        self._file_type_label.setText(self.tr("Playlist file type"))
        for index in range(self.file_type.count()):
            value = PlaylistFileType(self.file_type.itemData(index))
            self.file_type.setItemText(index, self._file_type_text(value))
        self._description.setText(
            self.tr(
                "Choose whether the Playlist should keep pointing to the mounted "
                "iPod or travel with exported copies of its %n track occurrence(s).",
                None,
                self._track_count,
            )
        )
        self.device_references.setText(
            self.tr(
                "Reference Tracks on the iPod — quick, but the Playlist works only "
                "while this iPod is mounted"
            )
        )
        self.copy_tracks.setText(
            self.tr(
                "Copy Tracks — export self-contained media files with Library "
                "metadata and cover artwork beside the Playlist"
            )
        )
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._continue.setText(self.tr("Choose Folder…"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _file_type_text(self, value: PlaylistFileType) -> str:
        return {
            PlaylistFileType.M3U8: self.tr("M3U8 — UTF-8 Extended M3U"),
            PlaylistFileType.M3U: self.tr("M3U — Extended M3U"),
            PlaylistFileType.PLS: "PLS",
            PlaylistFileType.XSPF: "XSPF",
            PlaylistFileType.WPL: "WPL — Windows Media Player",
        }[value]


__all__ = ["PlaylistExportDialog"]
