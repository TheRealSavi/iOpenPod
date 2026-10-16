"""Nano 6 application preparation carries the native image creation policy."""

from dataclasses import replace
from pathlib import Path

from tests.iOpenPod.app.services.test_library_resources import Device
from tests.iPodDB.library.test_write_artwork import BLUE
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from storage import HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform


def test_nano6_review_uses_original_artwork_creation_structure(tmp_path: Path) -> None:
    root = tmp_path / "ipod"
    original = {
        "iPod_Control/iTunes/iTunesCDB": compress_iTunesCDB(
            library().serialize().itunes
        )
    }
    for relative, data in original.items():
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
    metadata = root / "iPod_Control/Device"
    metadata.mkdir()
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MC688\nFirewireGuid: 000A270012345678\n", encoding="utf-8"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC, transport_serial="000A270012345678"
        ),
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    coordinator = DeviceCoordinator(storage, volume_presentation_enabled=False)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    device = Device(root, storage, platform, coordinator, original)
    try:
        first, second = device.active.library.tracks
        review = device.prepare(
            replace(
                device.active.library,
                tracks=(replace(first, artwork_id=BLUE.artwork_id), second),
            ),
            cover=True,
        )
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.artwork is not None
        document = parse_ArtworkDB(review.result.prepared.artwork)
        assert document.header.unk_mhfd_0x10 == 2
        image = document.find_chunks(MhiiHeader)[0].chunk
        assert tuple(
            child.header.mhod_type
            for child in image.children
            if isinstance(child.header, MhodHeader)
        ) == (2, 2, 2, 2)
        device.assert_original()
    finally:
        device.coordinator.close()
