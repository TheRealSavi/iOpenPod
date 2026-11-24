"""Device Picker presents connected devices and their actionable issues."""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
)

from device_registry import IdentificationStatus
from iOpenPod.app.models.device import (
    DeviceCandidate,
    DeviceCandidateId,
    DeviceCandidateIssue,
    DeviceCandidateIssueCode,
    DeviceDiscovery,
    DeviceReadiness,
)
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.widgets.storage_breakdown import format_capacity


def test_picker_sizes_to_connected_devices_and_keeps_keyboard_selection() -> None:
    application = QApplication.instance() or QApplication([])
    candidate = DeviceCandidate(
        id=DeviceCandidateId("one"),
        display_name="My iPod",
        host_description="iPod classic",
        bus="virtual",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=None,
        total_bytes=120_000_000_000,
        available_bytes=0,
    )
    second = replace(candidate, id=DeviceCandidateId("two"), display_name="Office")
    picker = DevicePickerDialog()
    selected: list[str] = []
    picker.deviceSelected.connect(selected.append)
    try:
        picker.show()
        devices = picker.findChild(QListWidget, "deviceCandidateList")
        empty = picker.findChild(QLabel, "devicePickerEmpty")
        detail = picker.findChild(QLabel, "deviceCandidateDetail")
        refresh = picker.findChild(QToolButton)
        assert devices is not None and empty is not None and detail is not None
        assert refresh is not None and refresh.accessibleName() == "Refresh"
        assert empty.isVisible() and devices.isHidden()
        refreshed = QSignalSpy(picker.refreshRequested)
        refresh.click()
        assert refreshed.count() == 1

        picker.set_discovery(DeviceDiscovery((candidate,)))
        application.processEvents()
        assert devices.isVisible() and empty.isHidden() and detail.isHidden()
        item = devices.item(0)
        assert item.text() == candidate.display_name
        description = item.data(Qt.ItemDataRole.AccessibleDescriptionRole)
        assert candidate.host_description in description
        assert format_capacity(candidate.total_bytes) in description
        assert "Ready to load" in description
        single_row_height = devices.viewport().height()
        assert single_row_height == devices.visualItemRect(item).height()
        with_artwork = devices.viewport().grab().toImage()
        item.setIcon(QIcon())
        assert devices.viewport().grab().toImage() != with_artwork

        picker.set_discovery(DeviceDiscovery((candidate, second)))
        application.processEvents()
        assert devices.viewport().height() >= 2 * single_row_height
        devices.setFocus()
        QTest.keyClick(devices, Qt.Key.Key_Down)
        picker.set_discovery(DeviceDiscovery((second, candidate)))
        assert devices.currentItem().text() == "Office"
        QTest.keyClick(devices, Qt.Key.Key_Return)
        assert selected == ["two"]
    finally:
        picker.close()


@pytest.mark.parametrize("earlier_issue", [False, True])
def test_picker_shows_every_appearance_failure_and_clears_resolved_details(
    earlier_issue: bool,
) -> None:
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    reasons = (
        "Could not update the Volume label: access denied",
        "Could not read <b>autorun.inf</b>",
        "Volume flush could not open the Volume: 5",
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("test-device"),
        display_name="My iPod",
        host_description="Test iPod",
        bus="virtual",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=None,
        total_bytes=1024,
        available_bytes=512,
        issues=(
            *(
                (
                    DeviceCandidateIssue(
                        DeviceCandidateIssueCode.PHOTOS_DATABASE_UNREADABLE
                    ),
                )
                if earlier_issue
                else ()
            ),
            *(
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE, reason
                )
                for reason in reasons
            ),
        ),
    )
    picker = DevicePickerDialog()
    try:
        picker.set_discovery(DeviceDiscovery(candidates=(candidate,)))
        detail = picker.findChild(QLabel, "deviceCandidateDetail")
        assert detail is not None
        for reason in reasons:
            assert reason in detail.text()
        assert "desktop name or icon could not be fully updated" in detail.text()
        assert ("Photos could not be loaded." in detail.text()) is earlier_issue
        assert detail.textFormat() == Qt.TextFormat.PlainText

        picker.set_discovery(
            DeviceDiscovery(candidates=(replace(candidate, issues=()),))
        )
        assert all(reason not in detail.text() for reason in reasons)
        assert detail.isHidden()
    finally:
        picker.close()


def test_picker_offers_missing_library_initialization() -> None:
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    candidate = DeviceCandidate(
        id=DeviceCandidateId("restored-ipod"),
        display_name="Restored iPod",
        host_description="Test iPod",
        bus="virtual",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.DATABASE_INITIALIZABLE,
        profile=None,
        total_bytes=1024,
        available_bytes=1024,
    )
    picker = DevicePickerDialog()
    try:
        picker.set_discovery(DeviceDiscovery(candidates=(candidate,)))
        detail = picker.findChild(QLabel, "deviceCandidateDetail")
        assert detail is not None
        assert "Select to create the missing iPod Library" in detail.text()
        select = next(
            button
            for button in picker.findChildren(QPushButton)
            if button.text() == "Use This iPod"
        )
        assert select.isEnabled()
    finally:
        picker.close()


def test_picker_preserves_host_recovery_error_as_selectable_plain_text() -> None:
    application = QApplication.instance() or QApplication([])
    candidate = DeviceCandidate(
        id=DeviceCandidateId("failed-access"),
        display_name="iPod",
        host_description="",
        bus="usb",
        identification_status=IdentificationStatus.UNKNOWN,
        readiness=DeviceReadiness.INSPECTION_FAILED,
        profile=None,
        total_bytes=1024,
        available_bytes=512,
        issues=(
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.INSPECTION_FAILED,
                "Could not validate Host recovery storage at /home/<user>/.config: access denied",
            ),
        ),
    )
    picker = DevicePickerDialog()
    try:
        picker.set_discovery(DeviceDiscovery(candidates=(candidate,)))
        detail = picker.findChild(QLabel, "deviceCandidateDetail")
        assert detail is not None
        assert "Host recovery storage" in detail.text()
        assert "<user>" in detail.text()
        assert detail.textFormat() == Qt.TextFormat.PlainText
        assert (
            detail.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        )
        select = next(
            button
            for button in picker.findChildren(QPushButton)
            if button.text() == "Use This iPod"
        )
        assert not select.isEnabled()
        application.processEvents()
    finally:
        picker.close()
