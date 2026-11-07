"""Linux discovery reaches identity setup after validating layered Host recovery."""

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from tests.storage.linux_mount_test_support import linux_recovery_layout

from iOpenPod.app.models.device import DeviceCandidateIssueCode, DeviceReadiness
from iOpenPod.app.services.device_coordinator import DeviceCoordinator


@pytest.mark.parametrize("mapped", [False, True])
def test_linux_discovery_with_host_recovery_retains_actionable_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mapped: bool,
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    device = layout.ipod / "iPod_Control" / "Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text("ModelNumStr: MC293\n", encoding="utf-8")
    database = layout.ipod / "iPod_Control" / "iTunes" / "iTunesDB"
    database.parent.mkdir()
    # Discovery checks existence/size; this test never selects or parses a Library.
    database.write_bytes(b"discovery placeholder")
    if not mapped:
        layout.records[1] = replace(
            layout.records[1], filesystem_type="unknown-overlay"
        )
    coordinator = DeviceCoordinator(layout.storage)
    caplog.set_level(logging.WARNING)
    try:
        candidate = coordinator.discover_devices().candidates[0]
        if mapped:
            assert candidate.readiness is DeviceReadiness.READY
            assert any(
                issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
                for issue in candidate.issues
            )
        else:
            assert candidate.readiness is DeviceReadiness.INSPECTION_FAILED
            assert "Host recovery storage" in candidate.issues[0].detail
            assert "Host recovery storage" in caplog.text
            failures = [
                record
                for record in caplog.records
                if "Could not prepare device access" in record.message
            ]
            assert len(failures) == 1
            coordinator.discover_devices()
            assert (
                len(
                    [
                        record
                        for record in caplog.records
                        if "Could not prepare device access" in record.message
                    ]
                )
                == 1
            )
    finally:
        coordinator.close()
