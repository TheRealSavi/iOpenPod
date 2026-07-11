import json
from types import SimpleNamespace

from iopenpod.application.jobs import (
    backup_device_name_from_playlists,
    build_backup_device_context,
    build_backup_device_meta,
    ensure_backup_folder,
    list_backup_devices_for_view,
)
from iopenpod.sync.backup_manager import BackupManager


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


def test_build_backup_device_context_prefers_library_device_name_override() -> None:
    device = SimpleNamespace(
        serial="SERIAL",
        firewire_guid="",
        ipod_name="iPod",
        display_name="iPod Classic",
        model_family="iPod Classic",
        generation="7th Gen",
        color="Black",
    )

    context = build_backup_device_context(
        "E:/",
        device,
        device_name="RoadPod",
    )

    assert context.device_name == "RoadPod"


def test_backup_device_name_from_playlists_reads_master_playlist_title() -> None:
    assert backup_device_name_from_playlists(
        [
            {"Title": "Regular Playlist"},
            {"master_flag": True, "Title": "RoadPod"},
        ]
    ) == "RoadPod"


def test_backup_device_name_from_playlists_ignores_dataset5_category_master() -> None:
    assert backup_device_name_from_playlists(
        [
            {
                "master_flag": True,
                "Title": "Rentals",
                "_source": "category",
                "mhsd5_type": 7,
            },
            {"master_flag": True, "Title": "RoadPod"},
        ]
    ) == "RoadPod"


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


def test_list_backup_devices_refreshes_connected_device_name_in_manifests(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    snapshots_dir = backup_dir / "CONNECTED" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    manifest_path = snapshots_dir / "20260101_120000.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "20260101_120000",
                "timestamp": "2026-01-01T12:00:00",
                "device_id": "CONNECTED",
                "device_name": "Old Name",
                "device_meta": {"family": "iPod Nano", "display_name": "iPod Nano"},
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    connected = SimpleNamespace(
        serial="CONNECTED",
        firewire_guid="",
        ipod_name="New Name",
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

    assert inventory.devices[0]["device_name"] == "New Name"
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["device_name"] == "New Name"
    assert updated["device_meta"] == {
        "family": "iPod Nano",
        "generation": "4th Gen",
        "color": "Blue",
        "display_name": "iPod Nano",
    }


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


def test_backup_no_changes_refreshes_existing_snapshot_device_name(tmp_path) -> None:
    ipod_root = tmp_path / "ipod"
    music_dir = ipod_root / "iPod_Control" / "Music" / "F00"
    music_dir.mkdir(parents=True)
    (music_dir / "TRACK.m4a").write_bytes(b"audio")
    backup_dir = tmp_path / "backups"

    old_manager = BackupManager(
        "DEVICE",
        backup_dir=str(backup_dir),
        device_name="Old Name",
        device_meta={"family": "iPod Classic"},
    )
    first_snapshot = old_manager.create_backup(ipod_root)
    assert first_snapshot is not None

    new_manager = BackupManager(
        "DEVICE",
        backup_dir=str(backup_dir),
        device_name="New Name",
        device_meta={"family": "iPod Classic", "generation": "7th Gen"},
    )
    second_snapshot = new_manager.create_backup(ipod_root)

    assert second_snapshot is None
    manifest_path = backup_dir / "DEVICE" / "snapshots" / f"{first_snapshot.id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["device_name"] == "New Name"
    assert manifest["device_meta"] == {
        "family": "iPod Classic",
        "generation": "7th Gen",
    }
