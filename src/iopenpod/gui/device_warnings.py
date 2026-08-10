"""User-facing warnings for devices that cannot be activated safely."""

from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.device_identity import linux_identity_setup_guidance

GITHUB_IDENTIFICATION_ISSUE_URL = (
    "https://github.com/TheRealSavi/iOpenPod/issues/new?template=bug_report.md"
)
_AUTOMATIC_WARNING_KEYS: set[str] = set()


def claim_unidentified_ipod_auto_prompt(ipod: object | None) -> bool:
    """Claim one application-scoped automatic warning for this device."""

    if ipod is None:
        return False
    key = str(
        getattr(ipod, "firewire_guid", "")
        or getattr(ipod, "path", "")
        or ""
    ).strip().upper()
    if not key:
        return True
    if key in _AUTOMATIC_WARNING_KEYS:
        return False
    _AUTOMATIC_WARNING_KEYS.add(key)
    return True


class LinuxIdentitySetupReviewDialog(QDialog):
    """Visible, keyboard-accessible review of privileged host commands."""

    def __init__(
        self,
        parent: QWidget | None,
        setup_instructions: str,
        *,
        after_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Linux iPod Identification Setup")
        self.setMinimumSize(680, 440)
        self.resize(760, 480)
        self._after_close = after_close
        self._close_notified = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        explanation = QLabel(
            "Copy these commands into a host terminal and run them. They install "
            "the iOpenPod udev rule and trigger only the selected iPod block device."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.commands = QPlainTextEdit(setup_instructions)
        self.commands.setReadOnly(True)
        self.commands.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.commands.setAccessibleName("Linux iPod host setup commands")
        self.commands.setAccessibleDescription(
            "Read-only commands that will be copied to a host terminal."
        )
        layout.addWidget(self.commands)

        self._copy_status_label: QLabel = QLabel("")
        self._copy_status_label.setAccessibleName("Copy status")
        layout.addWidget(self._copy_status_label)

        self._next_step_label = QLabel(
            "When you're finished, close this window to scan for your iPod again."
        )
        self._next_step_label.setWordWrap(True)
        layout.addWidget(self._next_step_label)

        self._buttons = QDialogButtonBox()
        copy_button = self._buttons.addButton(
            "Copy Commands",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        if copy_button is not None:
            copy_button.clicked.connect(self._copy_commands)
        done_button = self._buttons.addButton(
            "Done",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        if done_button is not None:
            done_button.clicked.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self.finished.connect(self._notify_after_close)
        layout.addWidget(self._buttons)

    def _copy_commands(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._copy_status_label.setText(
                "Clipboard unavailable. Select the commands and copy them manually."
            )
            return
        clipboard.setText(self.commands.toPlainText())
        self._copy_status_label.setText(
            "Commands copied. Paste them into a host terminal, review once "
            "more, and run them."
        )

    def _notify_after_close(self, _result: int) -> None:
        """Refresh the device picker once the user has completed the setup step."""

        if self._close_notified or self._after_close is None:
            return
        self._close_notified = True
        self._after_close()


def show_unidentified_ipod_warning(
    parent: QWidget | None,
    ipod: object | None,
    *,
    automatic: bool = False,
    after_close: Callable[[], None] | None = None,
) -> None:
    """Explain why an unidentified iPod cannot be selected and offer reporting."""

    if automatic and not claim_unidentified_ipod_auto_prompt(ipod):
        return

    mount = str(
        getattr(ipod, "mount_name", "")
        or getattr(ipod, "path", "")
        or "unknown mount"
    )
    firewire_guid = str(getattr(ipod, "firewire_guid", "") or "unknown")
    usb_pid = getattr(ipod, "usb_pid", 0)
    try:
        pid_text = f"0x{int(usb_pid):04X}" if usb_pid else "unknown"
    except (TypeError, ValueError):
        pid_text = str(usb_pid or "unknown")

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("iPod Identification Failed")
    linux_setup_button = None
    linux_setup = ""
    integration = linux_identity_setup_guidance(ipod, platform=sys.platform)
    if integration is not None:
        linux_setup = integration.setup_instructions
        message.setWindowTitle("Linux iPod Identification Setup")
        message.setText(
            "iOpenPod needs one-time Linux host setup to read this iPod's "
            "Apple product serial."
        )
        message.setInformativeText(
            f"{integration.explanation}\n\n"
            "Open the setup commands, copy them into a host terminal, and run "
            "them. When you finish, close the setup window and iOpenPod will "
            "scan for this iPod again. "
            "The setup installs a narrow udev rule that publishes only the "
            "serial; it does not grant raw-disk access or disconnect the iPod."
        )
        linux_setup_button = message.addButton(
            "View Setup Commands",
            QMessageBox.ButtonRole.ActionRole,
        )

    if linux_setup_button is None:
        message.setText(
            "iOpenPod could not determine this iPod's exact model number."
        )
        message.setInformativeText(
            "This device cannot be selected because using the wrong model "
            "profile could damage its databases or artwork. Please report "
            "this identification failure on GitHub and attach the iOpenPod log."
        )
        message.setDetailedText(
            f"Mount: {mount}\nUSB PID: {pid_text}\n"
            f"FireWire GUID: {firewire_guid}"
        )

    report_button = message.addButton(
        "Report Issue",
        QMessageBox.ButtonRole.ActionRole,
    )
    message.addButton(QMessageBox.StandardButton.Close)
    message.exec()
    clicked = message.clickedButton()
    if clicked is linux_setup_button and linux_setup:
        LinuxIdentitySetupReviewDialog(
            parent,
            linux_setup,
            after_close=after_close,
        ).exec()
    elif clicked is report_button:
        QDesktopServices.openUrl(QUrl(GITHUB_IDENTIFICATION_ISSUE_URL))
