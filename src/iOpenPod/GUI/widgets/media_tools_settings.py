"""Host media-tool path preferences, observed status, and optional setup access."""

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import MEDIA_TOOL_PATHS
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.services.media_tools import MediaToolSetup
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from storage import StorageError

_TOOLS = (("ffmpeg", "FFmpeg"), ("ffprobe", "FFProbe"), ("fpcalc", "FPCalc"))
_ENCODERS = (
    ("aac", "aac"),
    ("aac_at", "aac_at"),
    ("libfdk_aac", "libfdk_aac"),
    ("libmp3lame", "LAME (libmp3lame)"),
)


class MediaToolsSettings(QWidget):
    setupRequested = Signal()
    checkRequested = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, settings: SettingsService | None = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setMaximumWidth(960)
        self._setup: MediaToolSetup | None = None
        self._checking = False
        self._busy = False
        self._message = ""
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._summary = QLabel(self)
        self._summary.setObjectName("mediaToolsStatus")
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)
        self._tool_statuses: dict[str, QLabel] = {}
        self._tool_rows: dict[str, SettingRow] = {}
        self._encoder_statuses: dict[str, QLabel] = {}
        self._path_edits: dict[str, QLineEdit] = {}
        self._path_rows: dict[str, SettingRow] = {}
        self._path_buttons: dict[str, tuple[ActionButton, ActionButton]] = {}
        self._path_errors: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._summary)
        for name, title in _TOOLS:
            group = SettingGroup(self)
            status = self._status_label(f"mediaToolStatus_{name}")
            row = SettingRow(title, "", status, group)
            # Paths and process diagnostics must be displayed as plain text.
            for label in row.findChildren(QLabel):
                label.setTextFormat(Qt.TextFormat.PlainText)
            self._tool_statuses[name] = status
            self._tool_rows[name] = row
            group.add_row(row)
            if settings is not None:
                control = QWidget(group)
                path_layout = QVBoxLayout(control)
                path_layout.setContentsMargins(0, 0, 0, 0)
                path_layout.setSpacing(LAYOUT.space_xs)
                edit = QLineEdit(control)
                edit.setObjectName(f"mediaToolPath_{name}")
                edit.setText(settings.get_global(dict(MEDIA_TOOL_PATHS)[name]))
                edit.editingFinished.connect(partial(self._save_path, name))
                path_layout.addWidget(edit)
                actions = QHBoxLayout()
                browse = ActionButton(parent=control)
                browse.setObjectName(f"browseMediaTool_{name}")
                browse.clicked.connect(partial(self._browse_path, name))
                clear = ActionButton(parent=control)
                clear.setObjectName(f"clearMediaTool_{name}")
                clear.clicked.connect(partial(self._clear_path, name))
                actions.addWidget(browse)
                actions.addWidget(clear)
                path_layout.addLayout(actions)
                error = self._status_label(f"mediaToolPathError_{name}")
                error.hide()
                path_layout.addWidget(error)
                path_row = SettingRow("", "", control, group)
                group.add_row(path_row)
                self._path_edits[name] = edit
                self._path_rows[name] = path_row
                self._path_buttons[name] = browse, clear
                self._path_errors[name] = error
            if name == "ffmpeg":
                for encoder, encoder_label in _ENCODERS:
                    encoder_status = self._status_label(f"mediaEncoderStatus_{encoder}")
                    self._encoder_statuses[encoder] = encoder_status
                    group.add_row(SettingRow(encoder_label, "", encoder_status, group))
            layout.addWidget(group)
        buttons = QHBoxLayout()
        self._check = ActionButton(parent=self)
        self._check.setObjectName("refreshMediaTools")
        self._check.clicked.connect(self.checkRequested.emit)
        self._install = ActionButton(parent=self)
        self._install.setObjectName("setupMediaTools")
        self._install.clicked.connect(self.setupRequested.emit)
        buttons.addWidget(self._check)
        buttons.addWidget(self._install)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        if settings is not None:
            settings.settingChanged.connect(self._path_changed)
        self.retranslate_ui()

    def _save_path(self, name: str) -> None:
        if self._settings is None:
            return
        edit = self._path_edits[name]
        value = edit.text().strip()
        definition = dict(MEDIA_TOOL_PATHS)[name]
        error = self._path_errors[name]
        try:
            value = str(Path(value).expanduser()) if value else ""
            if not definition.validate(value):
                raise ValueError(
                    self.tr(
                        "Enter an absolute executable path, or clear it to use automatic discovery."
                    )
                )
            if value != self._settings.get_global(definition) or not error.isHidden():
                self._settings.set_global(definition, value)
        except (ValueError, RuntimeError, OSError, StorageError) as problem:
            error.setText(str(problem))
            error.show()
            return
        edit.setText(value)
        error.hide()

    def _browse_path(self, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose %1 executable").replace("%1", name),
            self._path_edits[name].text(),
            self.tr("All Files (*)"),
        )
        if path:
            self._path_edits[name].setText(path)
            self._save_path(name)

    def _clear_path(self, name: str) -> None:
        self._path_edits[name].clear()
        self._save_path(name)

    def _path_changed(self, key: str, value: object) -> None:
        for name, definition in MEDIA_TOOL_PATHS:
            if key == definition.key:
                self._path_edits[name].setText(str(value))
                self._path_errors[name].hide()
                self.checkRequested.emit()
                return

    def _status_label(self, name: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def set_status(
        self, setup: MediaToolSetup | None, *, checking: bool, busy: bool, message: str
    ) -> None:
        self._setup, self._checking, self._busy, self._message = (
            setup,
            checking,
            busy,
            message,
        )
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Media Tools"))
        self._check.setText(self.tr("Check Again"))
        self._install.setText(self.tr("Set Up Media Tools"))
        self._summary.setText(
            self.tr("Checking media tools…") if self._checking else self._message
        )
        tools = {tool.name: tool for tool in self._setup.tools} if self._setup else {}
        for name, title in _TOOLS:
            if name in self._path_edits:
                edit = self._path_edits[name]
                edit.setPlaceholderText(self.tr("Automatic discovery"))
                edit.setAccessibleName(self.tr("%1 path override").replace("%1", title))
                edit.setEnabled(not self._busy)
                browse, clear = self._path_buttons[name]
                browse.setText(self.tr("Browse…"))
                clear.setText(self.tr("Clear"))
                browse.setEnabled(not self._busy)
                clear.setEnabled(not self._busy)
                self._path_rows[name].set_copy(
                    self.tr("Path Override"),
                    self.tr(
                        "Choose an executable on this computer. Leave empty for automatic discovery."
                    ),
                )
            tool = tools.get(name)
            state = self.tr("Not checked")
            if self._checking:
                state = self.tr("Checking…")
            elif tool is not None:
                state = (
                    self.tr("Missing")
                    if not tool.path
                    else self.tr("Needs attention")
                    if tool.problem
                    else self.tr("Installed")
                )
            self._tool_statuses[name].setText(state)
            detail = (
                "\n".join(
                    value
                    for value in (
                        tool.path,
                        self.tr("Version: %1").replace("%1", tool.version)
                        if tool.version
                        else "",
                        tool.problem,
                        tool.encoder_problem,
                    )
                    if value
                )
                if tool
                else ""
            )
            self._tool_rows[name].set_copy(title, detail)
        ffmpeg = tools.get("ffmpeg")
        for encoder, status in self._encoder_statuses.items():
            state = self.tr("Not checked")
            if self._checking:
                state = self.tr("Checking…")
            elif ffmpeg is not None:
                if not ffmpeg.path:
                    state = self.tr("Unavailable")
                elif ffmpeg.encoders is None or ffmpeg.problem:
                    state = self.tr("Unknown")
                else:
                    state = (
                        self.tr("Available")
                        if encoder in ffmpeg.encoders
                        else self.tr("Unavailable")
                    )
            status.setText(state)
        self._check.setEnabled(not self._busy)
        self._install.setVisible(
            not self._checking and any(not tool.path for tool in tools.values())
        )
        self._install.setEnabled(not self._busy)
