"""User-facing warnings for devices that cannot be activated safely."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QWidget

GITHUB_IDENTIFICATION_ISSUE_URL = (
    "https://github.com/TheRealSavi/iOpenPod/issues/new?template=bug_report.md"
)


def show_unidentified_ipod_warning(
    parent: QWidget | None,
    ipod: object | None,
) -> None:
    """Explain why an unidentified iPod cannot be selected and offer reporting."""

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
    message.setText("iOpenPod could not determine this iPod's exact model number.")
    message.setInformativeText(
        "This device cannot be selected because using the wrong model profile "
        "could damage its databases or artwork. Please report this identification "
        "failure on GitHub and attach the iOpenPod log."
    )
    message.setDetailedText(
        f"Mount: {mount}\nUSB PID: {pid_text}\nFireWire GUID: {firewire_guid}"
    )
    report_button = message.addButton(
        "Report on GitHub",
        QMessageBox.ButtonRole.ActionRole,
    )
    message.addButton(QMessageBox.StandardButton.Close)
    message.exec()
    if message.clickedButton() is report_button:
        QDesktopServices.openUrl(QUrl(GITHUB_IDENTIFICATION_ISSUE_URL))
