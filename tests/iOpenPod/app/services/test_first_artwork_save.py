"""First cover publication needs only an identified iPod and its iTunesDB."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device
from tests.iPodDB.library.test_write_artwork import BLUE
from tests.iPodDB.library.test_writing import library

from device_registry import DEFAULT_DEVICE_REGISTRY, DatabaseChecksum
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.library import CoverFormat, CoverPixelFormat, IPodLibrary
from storage import HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform

SUPPORTED_MODELS = tuple(
    {
        (profile.family, profile.generation): profile.model_number
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.capabilities.artwork.supports_cover_art
        and profile.capabilities.database.checksum
        in (DatabaseChecksum.NONE, DatabaseChecksum.HASH58)
        and not profile.capabilities.database.supports_compressed_database
        and not profile.capabilities.database.uses_sqlite_database
    }.values()
)


def bare_device(tmp_path: Path, model_number: str = "MB565") -> Device:
    root = tmp_path / "ipod"
    original = {"iPod_Control/iTunes/iTunesDB": library().serialize().itunes}
    for relative, data in original.items():
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
    metadata = root / "iPod_Control/Device"
    metadata.mkdir()
    (metadata / "SysInfo").write_text(
        f"ModelNumStr: {model_number}\nFirewireGuid: 000A270012345678\n",
        encoding="utf-8",
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            transport_serial="000A270012345678",
        ),
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    coordinator = DeviceCoordinator(storage)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert coordinator.active_ipod is not None
    assert coordinator.active_ipod.profile.model_number == model_number
    return Device(root, storage, platform, coordinator, original)


@pytest.mark.parametrize("empty_directory", [False, True])
@pytest.mark.parametrize("model_number", SUPPORTED_MODELS)
def test_first_artworkdb_creates_every_cover_and_can_be_restored(
    tmp_path: Path, empty_directory: bool, model_number: str
) -> None:
    device = bare_device(tmp_path, model_number)
    try:
        directory = device.root / "iPod_Control/Artwork"
        if empty_directory:
            directory.mkdir()
        assert device.active.artwork_database_fingerprint is None
        first, second = device.active.library.tracks
        desired = replace(
            device.active.library,
            tracks=(replace(first, artwork_id=BLUE.artwork_id), second),
        )
        review = device.prepare(desired, cover=True)
        assert review.result.prepared is not None, review.result.issues
        prepared = review.result.prepared
        assert prepared.artwork is not None
        document = parse_ArtworkDB(prepared.artwork)
        assert document.header.unk_mhfd_0x10 == 6
        assert document.header.next_mhii_id == 101
        formats = device.active.profile.capabilities.artwork.cover_formats
        assert {s.chunk.header.format_id for s in document.find_chunks(MhifHeader)} == {
            f.format_id for f in formats
        }
        assert len(prepared.artwork_files) == len(formats)
        assert not (directory / "ArtworkDB").exists()
        assert directory.exists() == empty_directory
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        reread = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        ).with_artwork((directory / "ArtworkDB").read_bytes())
        assert reread.snapshot == saved.active.library
        assert reread.snapshot.tracks[1] == second
        for fmt in formats:
            read = reread.artwork_read(
                reread.snapshot.tracks[0].artwork_id,
                (
                    CoverFormat(
                        fmt.format_id,
                        fmt.width,
                        fmt.height,
                        fmt.row_bytes,
                        CoverPixelFormat(fmt.pixel_format.value),
                    ),
                ),
                fmt.width,
            )
            assert read is not None
            payload = (device.root / read.relative_path).read_bytes()
            pixels = read.decode(payload[read.offset : read.offset + read.length])
            assert (pixels.width, pixels.height) == (fmt.width, fmt.height)
            assert pixels.rgb888 == bytes((0, 0, 255)) * (fmt.width * fmt.height)
        device.restore(saved.recovery_path)
        assert not (directory / "ArtworkDB").exists()
        assert not tuple(directory.glob("*.ithmb"))
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("filename", ["ArtworkDB", "F1055_1.ithmb"])
def test_first_save_does_not_overwrite_files_that_appeared_after_review(
    tmp_path: Path, filename: str
) -> None:
    device = bare_device(tmp_path)
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
        path = device.root / "iPod_Control/Artwork" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"externally created file")
        saved = device.save(review)
        assert saved.active is None
        assert path.read_bytes() == b"externally created file"
        device.assert_original()
    finally:
        device.coordinator.close()
