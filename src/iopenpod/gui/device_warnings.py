"""User-facing warnings for devices that cannot be activated safely."""

from __future__ import annotations

import sys

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
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Linux iPod Setup")
        self.resize(760, 480)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Review these host commands before copying them. They install the "
            "iOpenPod udev rule and trigger only the selected iPod block device."
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_button = buttons.addButton(
            "Copy Commands",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        if copy_button is not None:
            copy_button.clicked.connect(self._copy_commands)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_commands(self) -> None:
        QApplication.clipboard().setText(self.commands.toPlainText())
        self._copy_status_label.setText(
            "Commands copied. Paste them into a host terminal, review once "
            "more, and run them."
        )


def show_unidentified_ipod_warning(
    parent: QWidget | None,
    ipod: object | None,
    *,
    automatic: bool = False,
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
            "Copy the setup below and run it in a host terminal. Then return "
            "to iOpenPod, open Select Device if needed, and click Rescan. "
            "The setup installs a narrow udev rule that publishes only the "
            "serial; it does not grant raw-disk access or disconnect the iPod."
        )
        message.setDetailedText(linux_setup)
        linux_setup_button = message.addButton(
            "Review Linux Setup",
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
        "Report on GitHub",
        QMessageBox.ButtonRole.ActionRole,
    )
    message.addButton(QMessageBox.StandardButton.Close)
    message.exec()
    clicked = message.clickedButton()
    if clicked is linux_setup_button and linux_setup:
        LinuxIdentitySetupReviewDialog(parent, linux_setup).exec()
    elif clicked is report_button:
        QDesktopServices.openUrl(QUrl(GITHUB_IDENTIFICATION_ISSUE_URL))
