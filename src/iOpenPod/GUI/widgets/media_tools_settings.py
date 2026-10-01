"""Read-only media-tool and encoder status with optional setup access."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from iOpenPod.app.services.media_tools import MediaToolSetup
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self.retranslate_ui()

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
                    for value in (tool.path, tool.problem, tool.encoder_problem)
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
