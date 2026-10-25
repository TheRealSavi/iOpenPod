"""Device Picker exposes actionable appearance failures as literal text."""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

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
                (DeviceCandidateIssue(DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN),)
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
        assert detail.textFormat() == Qt.TextFormat.PlainText

        picker.set_discovery(
            DeviceDiscovery(candidates=(replace(candidate, issues=()),))
        )
        assert all(reason not in detail.text() for reason in reasons)
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
