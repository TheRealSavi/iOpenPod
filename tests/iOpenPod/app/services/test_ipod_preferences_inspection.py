"""Read-only selection snapshots preserve optional-file and disconnect semantics."""

import struct
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
    _RecordingStorage,  # pyright: ignore[reportPrivateUsage]
)

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.models.ipod_preferences import PreferenceFileStatus
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceCoordinator,
)
from iOpenPod.app.services.ipod_preferences import read_ipod_preferences
from storage import AccessMode, DevicePath, FileSnapshot, FilesystemSession, Storage
from storage.testing import VirtualStoragePlatform


def _install_preferences(root: Path) -> tuple[bytes, bytes]:
    device = bytearray(2956)
    struct.pack_into("<h", device, 0xB70, 0x21)
    itunes = bytearray(1232)
    itunes[:4] = b"frpd"
    itunes[9] = 254
    itunes[11] = 2
    itunes[89] = 1
    itunes[90] = 1
    itunes[12:20] = b"libraryA"
    itunes[96:104] = b"libraryB"
    (root / "iPod_Control/Device/Preferences").write_bytes(device)
    (root / "iPod_Control/iTunes/iTunesPrefs").write_bytes(itunes)
    return bytes(device), bytes(itunes)


def test_selection_loads_both_preference_files_without_writing(tmp_path: Path) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    device, itunes = _install_preferences(root)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)
    try:
        candidate = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(candidate.id, reconcile_metadata=False)
        firmware, sync = active.preferences
        assert firmware.status is sync.status is PreferenceFileStatus.AVAILABLE
        device_values = {row.key: row.value for row in firmware.rows}
        sync_values = {row.key: row.value for row in sync.rows}
        assert device_values["timezone"] == "America/Detroit"
        assert device_values["language"] == "English"
        assert "Not decoded" in device_values["volume_limit"]
        assert sync_values["open_itunes"] == "Unknown (code 254)"
        assert sync_values["music_sync_mode"] == "Manual"
        assert sync_values["music_sync_selection"] == "Selected playlists"
        assert sync_values["podcast_sync_mode"] == "Automatic"
        assert sync_values["library_link"] != sync_values["secondary_library_link"]
        assert len(sync.rows) == 18
        assert set(storage.access_modes) == {AccessMode.READ_ONLY}
        assert (root / "iPod_Control/Device/Preferences").read_bytes() == device
        assert (root / "iPod_Control/iTunes/iTunesPrefs").read_bytes() == itunes
        platform.disconnect(root)
        coordinator.discover_devices()
        assert coordinator.active_ipod is None
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "data,status",
    (
        (None, PreferenceFileStatus.MISSING),
        (b"", PreferenceFileStatus.UNREADABLE),
        (b"unrecognized", PreferenceFileStatus.UNKNOWN),
        (bytes(1024 * 1024 + 1), PreferenceFileStatus.UNREADABLE),
    ),
    ids=("missing", "empty", "unknown", "oversized"),
)
def test_optional_file_problems_keep_other_settings_and_library_available(
    tmp_path: Path,
    data: bytes | None,
    status: PreferenceFileStatus,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    _install_preferences(root)
    path = root / "iPod_Control/Device/Preferences"
    if data is None:
        path.unlink()
    else:
        path.write_bytes(data)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id, reconcile_metadata=False
        )
        assert active.library.tracks
        assert active.preferences[0].status is status
        assert active.preferences[0].rows == ()
        assert active.preferences[0].detail
        assert active.preferences[1].status is PreferenceFileStatus.AVAILABLE
    finally:
        coordinator.close()


def test_disconnect_during_preferences_read_aborts_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    _install_preferences(root)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    read = FilesystemSession.read_snapshot

    def disconnect(
        self: FilesystemSession, path: DevicePath, *, max_bytes: int
    ) -> FileSnapshot:
        if path.name == "Preferences":
            platform.disconnect(root)
        return read(self, path, max_bytes=max_bytes)

    monkeypatch.setattr(FilesystemSession, "read_snapshot", disconnect)
    try:
        with pytest.raises(DeviceAccessError):
            coordinator.select_device(candidate.id, reconcile_metadata=False)
        assert coordinator.active_ipod is None
    finally:
        coordinator.close()


def test_model_specific_dst_and_unknown_city_are_not_guessed(tmp_path: Path) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MA978")
    data = bytearray(2952)
    data[0x6BC] = 60
    (root / "iPod_Control/Device/Preferences").write_bytes(data)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MA978")
    assert profile is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        firmware, itunes = read_ipod_preferences(session, profile)
    rows = {row.key: row.value for row in firmware.rows}
    assert rows["timezone"] == "Unknown (city 0)"
    assert rows["daylight_saving"] == "On"
    assert itunes.status is PreferenceFileStatus.MISSING
