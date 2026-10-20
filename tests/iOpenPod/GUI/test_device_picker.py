"""Device Picker exposes actionable appearance failures as literal text."""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

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
