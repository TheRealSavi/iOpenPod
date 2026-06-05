import json
from types import SimpleNamespace

from app_core.jobs import (
    build_backup_device_context,
    build_backup_device_meta,
    ensure_backup_folder,
    list_backup_devices_for_view,
)
from SyncEngine.backup_manager import BackupManager


def test_build_backup_device_context_sanitizes_identity_and_copies_meta() -> None:
    device = SimpleNamespace(
        serial="SERIAL:123",
        firewire_guid="",
        ipod_name="RoadPod",
        display_name="iPod Classic",
        model_family="iPod Classic",
        generation="7th Gen",
        color="Black",
    )

    context = build_backup_device_context("E:/", device)

    assert context.device_id == "SERIAL_123"
    assert context.device_name == "RoadPod"
    assert context.device_meta == {
        "family": "iPod Classic",
        "generation": "7th Gen",
        "color": "Black",
        "display_name": "iPod Classic",
    }


def test_build_backup_device_meta_skips_missing_device() -> None:
    assert build_backup_device_meta(None) == {}


def test_list_backup_devices_includes_connected_device_first(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    snapshots_dir = backup_dir / "ARCHIVED" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    (snapshots_dir / "20260101_120000.json").write_text(
        json.dumps(
            {
                "device_name": "ArchivedPod",
                "device_meta": {"family": "iPod Mini"},
            }
        ),
        encoding="utf-8",
    )
    connected = SimpleNamespace(
        serial="CONNECTED",
        firewire_guid="",
        ipod_name="ConnectedPod",
        display_name="iPod Nano",
        model_family="iPod Nano",
        generation="4th Gen",
        color="Blue",
    )

    inventory = list_backup_devices_for_view(
        str(backup_dir),
        connected_ipod_path="E:/",
        connected_ipod_info=connected,
    )

    assert inventory.device_connected is True
    assert inventory.connected_device_id == "CONNECTED"
    assert [device["device_id"] for device in inventory.devices] == [
        "CONNECTED",
        "ARCHIVED",
    ]
    assert inventory.devices[0]["device_name"] == "ConnectedPod"
    assert inventory.devices[0]["snapshot_count"] == 0
    assert inventory.devices[1]["device_name"] == "ArchivedPod"


def test_ensure_backup_folder_prefers_existing_device_subfolder(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    device_dir = backup_dir / "DEVICE"
    device_dir.mkdir(parents=True)

    assert ensure_backup_folder(str(backup_dir), "DEVICE") == device_dir
    assert ensure_backup_folder(str(backup_dir), "MISSING") == backup_dir


def test_backup_walk_skips_macos_metadata_files(tmp_path) -> None:
    ipod_root = tmp_path / "ipod"
    music_dir = ipod_root / "iPod_Control" / "Music" / "F00"
    music_dir.mkdir(parents=True)
    (music_dir / "TRACK.m4a").write_bytes(b"audio")
    (music_dir / "._TRACK.m4a").write_bytes(b"sidecar")
    (ipod_root / ".metadata_never_index").write_bytes(b"")

    manager = BackupManager("DEVICE", backup_dir=str(tmp_path / "backups"))

    assert manager._walk_device(ipod_root) == [
        ("iPod_Control/Music/F00/TRACK.m4a", music_dir / "TRACK.m4a")
    ]
