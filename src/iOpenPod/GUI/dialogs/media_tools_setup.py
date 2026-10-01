"""Media dependency setup, progress, and recovery without blocking the GUI."""

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.media_tools_controller import MediaToolsController
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class MediaToolsSetupDialog(QDialog):
    def __init__(
        self, controller: MediaToolsController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("mediaToolsSetup")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(720, 520)
        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._explanation = QLabel(self)
        self._explanation.setWordWrap(True)
        self._tools = QLabel(self)
        self._tools.setObjectName("mediaToolStatus")
        self._tools.setTextFormat(Qt.TextFormat.PlainText)
        self._tools.setWordWrap(True)
        self._tools.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._channel = QLabel(self)
        self._channel.setWordWrap(True)
        self._channel.setTextFormat(Qt.TextFormat.PlainText)
        self._status = QLabel(self)
        self._status.setObjectName("mediaToolSetupStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._log = QPlainTextEdit(self)
        self._log.setObjectName("mediaToolInstallLog")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._close = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._check = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._help = buttons.addButton("", QDialogButtonBox.ButtonRole.HelpRole)
        self._install = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._stop = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._install.setObjectName("installMediaTools")
        self._check.setObjectName("checkMediaTools")
        self._stop.setObjectName("stopMediaToolInstall")
        apply_action_button_kind(self._install, ActionButtonKind.PRIMARY)
        for button in (self._close, self._check, self._help, self._stop):
            apply_action_button_kind(button, ActionButtonKind.SECONDARY)
            button.setAutoDefault(False)
        self._install.setAutoDefault(False)
        self._check.clicked.connect(controller.check)
        self._install.clicked.connect(controller.install)
        self._stop.clicked.connect(controller.stop_after_current)
        self._help.clicked.connect(self._open_help)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        for widget in (
            self._title,
            self._explanation,
            self._tools,
            self._channel,
            self._status,
            self._progress,
        ):
            layout.addWidget(widget)
        layout.addWidget(self._log, 1)
        layout.addWidget(buttons)
        controller.changed.connect(self._render)
        controller.output.connect(self._append_output)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Set Up Media Tools"))
        self._title.setText(self.tr("Set Up Media Tools"))
        self._explanation.setText(
            self.tr(
                "FFmpeg and FFprobe prepare and inspect media. Chromaprint's fpcalc enables acoustic matching. "
                "You can skip setup and keep browsing; acoustic matching is optional. "
                "Choose Install Missing Tools to let the selected package manager install them on this computer."
            )
        )
        self._check.setText(self.tr("Check Again"))
        self._help.setText(self.tr("Setup Help"))
        self._install.setText(self.tr("Install Missing Tools"))
        self._stop.setText(self.tr("Stop After Current Package"))
        self._log.setAccessibleName(self.tr("Package installation details"))
        self._log.setPlaceholderText(
            self.tr("Installation progress and errors will appear here.")
        )
        self._render()

    def _render(self) -> None:
        controller = self._controller
        setup = controller.setup
        self._tools.setText(
            "\n\n".join(
                f"{tool.name}: "
                + (
                    self.tr("Missing")
                    if not tool.path
                    else self.tr("Needs attention") + f" — {tool.path}\n{tool.problem}"
                    if tool.problem
                    else self.tr("Ready") + f" — {tool.path}"
                )
                for tool in setup.tools
            )
            if setup
            else ""
        )
        self._channel.setText(
            f"{setup.plan.channel}\n{workflow_text(setup.plan.explanation)}"
            if setup
            else ""
        )
        self._status.setText(
            self.tr("Checking media tools…")
            if controller.checking
            else controller.message
        )
        self._progress.setVisible(controller.busy)
        self._install.setEnabled(
            bool(setup and setup.plan.commands) and not controller.busy
        )
        self._install.setVisible(not controller.installing)
        self._check.setEnabled(not controller.busy)
        self._help.setEnabled(setup is not None and not controller.installing)
        self._close.setEnabled(not controller.installing)
        self._stop.setVisible(controller.installing)
        self._stop.setEnabled(not controller.stopping)

    def _append_output(self, text: str) -> None:
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        # Some tools emit progress on one line indefinitely.
        if self._log.document().characterCount() > 65536:
            self._log.setPlainText(self._log.toPlainText()[-49152:])
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _open_help(self) -> None:
        if self._controller.setup is not None:
            QDesktopServices.openUrl(QUrl(self._controller.setup.plan.help_url))

    def reject(self) -> None:
        if self._controller.installing:
            self._controller.stop_after_current()
            return
        super().reject()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
