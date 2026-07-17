from iopenpod.application.services import (
    DeviceCapabilitySnapshot,
    DeviceIdentitySnapshot,
    DeviceStorageSnapshot,
)


class FakeCapabilities:
    checksum = 58
    is_shuffle = False
    shadow_db_version = 0
    supports_compressed_db = False
    supports_video = True
    supports_podcast = False
    supports_gapless = True
    supports_artwork = True
    supports_photo = True
    supports_sparse_artwork = True
    supports_alac = True
    music_dirs = 50
    uses_sqlite_db = False
    db_version = 0x30
    byte_order = "le"
    has_screen = True
    max_video_width = 640
    max_video_height = 480
    max_video_fps = 30
    max_video_bitrate = 2500
    h264_level = "3.1"
    max_database_bytes = 64 * 1024 * 1024


class FakeDeviceInfo:
    path = "E:\\"
    mount_name = "E:"
    ipod_name = "RoadPod"
    display_name = "John's RoadPod"
    model_number = "MC297"
    model_family = "iPod Classic"
    generation = "3rd Gen"
    capacity = "160GB"
    color = "Black"
    serial = "SERIAL123"
    firewire_guid = "ABCDEF1234567890"
    reported_volume_format = "FAT32"
    filesystem_type = "vfat"
    volume_identity_key = "linux|8:2|IPOD-UUID|mount-42"
    max_file_size_gb = 4
    capabilities = FakeCapabilities()


def test_device_identity_snapshot_copies_device_fields() -> None:
    snapshot = DeviceIdentitySnapshot.from_device_info(FakeDeviceInfo())

    assert snapshot is not None
    assert snapshot.display_name == "John's RoadPod"
    assert snapshot.model_family == "iPod Classic"
    assert snapshot.serial == "SERIAL123"
    assert snapshot.firewire_guid == "ABCDEF1234567890"


def test_device_capability_snapshot_copies_device_capabilities() -> None:
    snapshot = DeviceCapabilitySnapshot.from_device_info(FakeDeviceInfo())

    assert snapshot is not None
    assert snapshot.supports_video is True
    assert snapshot.supports_podcast is False
    assert snapshot.music_dirs == 50
    assert snapshot.h264_level == "3.1"
    assert snapshot.max_database_bytes == 64 * 1024 * 1024


def test_device_storage_snapshot_keeps_reported_and_observed_formats_separate() -> None:
    snapshot = DeviceStorageSnapshot.from_device_info(FakeDeviceInfo())

    assert snapshot is not None
    assert snapshot.reported_volume_format == "FAT32"
    assert snapshot.scanned_filesystem_type == "vfat"
    assert snapshot.device_max_file_size_bytes == 4 * 1024**3
    assert snapshot.volume_identity_key == "linux|8:2|IPOD-UUID|mount-42"
