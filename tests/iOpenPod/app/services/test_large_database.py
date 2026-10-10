"""Regression coverage for large Classic libraries at device selection and Save."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceCoordinator,
)
from storage import HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("model_number, limit_mb", [("MC293", 64), ("MA444", 32)])
def test_database_above_hardware_limit_loads_but_cannot_be_saved(
    tmp_path: Path, model_number: str, limit_mb: int
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "ipod", model_number=model_number)
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    # A retained suffix keeps the fixture small to construct while exercising
    # real Storage reads, parsing, and preparation above the hardware limit.
    with database.open("ab") as output:
        output.truncate(limit_mb * 1024 * 1024 + 1)
    original_size = database.stat().st_size
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(transport_serial="000A270012345678"),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(candidate.id)

        assert (
            active.profile.capabilities.database.max_database_bytes
            == limit_mb * 1024**2
        )
        assert active.database_fingerprint.size == original_size
        assert active.library.tracks[0].title == "Blue Train"

        edited = replace(
            active.library,
            tracks=(replace(active.library.tracks[0], title="Large Library"),),
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(edited, active, 1, 1),
            lambda _progress: None,
            Event(),
        )
        assert review.result.prepared is None
        assert any(
            f"Your iPod's hardware can only support up to {limit_mb} MB in its database."
            in issue.message
            for issue in review.result.issues
        )
        assert database.stat().st_size == original_size
        assert active.library.tracks[0].title == "Blue Train"
    finally:
        coordinator.close()


def test_database_above_one_gib_is_rejected_before_reading(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MC293")
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    with database.open("ab") as output:
        output.truncate(1024**3 + 1)
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        with pytest.raises(DeviceAccessError, match="allowed read size of 1073741824"):
            coordinator.select_device(candidate.id)
    finally:
        coordinator.close()
