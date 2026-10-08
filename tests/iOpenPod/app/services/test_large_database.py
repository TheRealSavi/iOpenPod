"""Regression coverage for large Classic libraries at device selection and Save."""

from dataclasses import replace
from pathlib import Path
from threading import Event

from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.library import IPodLibrary
from storage import HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform


def test_classic_loads_and_saves_database_above_64_mib(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MC293")
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    # A retained suffix keeps the fixture small to construct while exercising
    # real Storage reads, parsing, preparation, and publication above the old cap.
    with database.open("ab") as output:
        output.truncate(64 * 1024 * 1024 + 1)
    original_size = database.stat().st_size
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(transport_serial="000A270012345678"),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(candidate.id)

        assert active.profile.generation == "7th Gen"
        assert active.profile.capabilities.database.max_database_bytes == 1024**3
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
        assert review.result.prepared is not None, review.result.issues

        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].title == "Large Library"
        assert database.stat().st_size > 64 * 1024 * 1024
        assert IPodLibrary.parse(database.read_bytes()).snapshot == saved.active.library
    finally:
        coordinator.close()
