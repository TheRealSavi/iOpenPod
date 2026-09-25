"""Review-and-copy workflow for one-time Linux iPod identification setup."""

from enum import StrEnum

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.services.linux_identity import (
    udev_setup_command,
    udev_uninstall_command,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class _LinuxUdevOperation(StrEnum):
    SETUP = "setup"
    UNINSTALL = "uninstall"


class _LinuxUdevCommandDialog(QDialog):
    """Show an exact privileged Host command before the user copies it."""

    def __init__(
        self,
        operation: _LinuxUdevOperation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._operation = operation
        self.setObjectName(
            "linuxIdentitySetup"
            if operation is _LinuxUdevOperation.SETUP
            else "linuxIdentityUninstall"
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(660, 460)
        self.resize(760, 520)

        self._title = QLabel(self)
        self._title.setObjectName("pageTitle")
        self._explanation = QLabel(self)
        self._explanation.setObjectName("pageDescription")
        self._explanation.setWordWrap(True)
        self._steps = QLabel(self)
        self._steps.setWordWrap(True)

        self._command = QPlainTextEdit(self)
        self._command.setObjectName("linuxIdentitySetupCommand")
        self._command.setReadOnly(True)
        self._command.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._command.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self._command.setPlainText(
            udev_setup_command()
            if operation is _LinuxUdevOperation.SETUP
            else udev_uninstall_command()
        )
        self._command.setAccessibleName(self.tr("Linux iPod udev command"))
        self._command.setAccessibleDescription(
            self.tr("Read-only command to copy into a Linux Host terminal.")
        )

        self._copy_status = QLabel(self)
        self._copy_status.setObjectName("linuxIdentitySetupStatus")
        self._copy_status.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        apply_action_button_kind(close, ActionButtonKind.SECONDARY)
        self._copy = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        apply_action_button_kind(
            self._copy,
            ActionButtonKind.PRIMARY
            if operation is _LinuxUdevOperation.SETUP
            else ActionButtonKind.DANGER,
        )
        self._copy.clicked.connect(self._copy_command)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._explanation)
        layout.addWidget(self._steps)
        layout.addWidget(self._command, 1)
        layout.addWidget(self._copy_status)
        layout.addWidget(buttons)
        self.retranslate_ui()

    @property
    def command(self) -> str:
        """Return the reviewed Host command exactly as displayed and copied."""

        return self._command.toPlainText()

    def retranslate_ui(self) -> None:
        if self._operation is _LinuxUdevOperation.SETUP:
            title = self.tr("Set Up Linux iPod Identification")
            explanation = self.tr(
                "Linux needs a one-time udev rule to read this iPod's Apple "
                "product serial. The rule publishes only that serial; it does "
                "not grant iOpenPod raw-disk access or change device permissions."
            )
            steps = self.tr(
                "1. Copy the command below.\n"
                "2. Paste it into a terminal on this Linux computer and run it.\n"
                "3. Safely eject the iPod completely in iOpenPod or the operating "
                "system.\n"
                "4. Physically disconnect and reconnect the iPod.\n"
                "5. Wait for the operating system to mount it again.\n"
                "6. Choose Refresh in iOpenPod's device picker.\n\n"
                "The command explicitly uses /bin/sh, so it also works when "
                "your terminal uses Fish or Zsh. Restarting or refreshing iOpenPod "
                "before the remount is not enough."
            )
            copy_text = self.tr("Copy Setup Command")
        else:
            title = self.tr("Uninstall Linux iPod Identification Rule")
            explanation = self.tr(
                "This removes only iOpenPod's local rule at "
                "/etc/udev/rules.d/61-iopenpod.rules and reloads udev. "
                "Package-managed rules under /usr or /lib are left untouched."
            )
            steps = self.tr(
                "1. Copy the reviewed command below.\n"
                "2. Paste it into a terminal on this Linux computer and run it.\n"
                "3. Safely eject, physically disconnect, and reconnect the iPod.\n"
                "4. Return to Settings and choose Check Again.\n\n"
                "Restarting iOpenPod does not clear properties already cached by "
                "udev. The command refuses to remove a directory or any other rule."
            )
            copy_text = self.tr("Copy Uninstall Command")
        self.setWindowTitle(title)
        self._title.setText(title)
        self._explanation.setText(explanation)
        self._steps.setText(steps)
        self._copy.setText(copy_text)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _copy_command(self) -> None:
        QApplication.clipboard().setText(self.command)
        self._copy_status.setText(
            self.tr("Copied. Paste the command into a terminal and run it.")
        )


class LinuxIdentitySetupDialog(_LinuxUdevCommandDialog):
    """Review the least-privilege Linux identity-rule setup command."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_LinuxUdevOperation.SETUP, parent)


class LinuxIdentityUninstallDialog(_LinuxUdevCommandDialog):
    """Review removal of only iOpenPod's local Linux identity rule."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_LinuxUdevOperation.UNINSTALL, parent)
