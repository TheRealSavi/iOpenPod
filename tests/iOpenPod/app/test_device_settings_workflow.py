"""Run settings publication through the real controller and virtual Storage."""

import json
from pathlib import Path
from threading import get_ident

import pytest
from tests.iOpenPod.app.test_device_controller import (
    _device_root,  # pyright: ignore[reportPrivateUsage]
    _wait_until,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.core.settings.definitions import COMPUTE_SOUND_CHECK, MAX_BACKUPS
from iOpenPod.app.core.settings.device import SETTINGS_PATH, DeviceSettings
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from storage import Storage
from storage.testing import VirtualStoragePlatform


class _ObservedCoordinator(DeviceCoordinator):
    save_thread: int | None = None

    def save_settings(
        self, expected: ActiveIPod, previous: DeviceSettings, values: dict[str, object]
    ) -> DeviceSettings:
        self.save_thread = get_ident()
        return super().save_settings(expected, previous, values)


def test_save_reset_reconnect_switch_and_disconnect(tmp_path: Path) -> None:
    first = _device_root(tmp_path / "first")
    second = _device_root(tmp_path / "second")
    platform = VirtualStoragePlatform()
    platform.add_volume(first, volume_id="first")
    platform.add_volume(second, volume_id="second", device_id="second")
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(COMPUTE_SOUND_CHECK, True)
    coordinator = _ObservedCoordinator(Storage(platform))
    controller = DeviceController(coordinator, TrackTableModel(), settings)
    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        candidates = controller.discovery.candidates
        controller.select_device(candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        assert settings.device_connected and settings.device_writable
        settings.set_device(COMPUTE_SOUND_CHECK, False)
        assert settings.device_busy and settings.get(COMPUTE_SOUND_CHECK) is True
        _wait_until(lambda: not controller.busy)
        assert coordinator.save_thread != get_ident()
        assert settings.get(COMPUTE_SOUND_CHECK) is False
        assert controller.reload_active_ipod()
        _wait_until(lambda: not controller.busy)
        assert settings.get(COMPUTE_SOUND_CHECK) is False
        settings.set_device(MAX_BACKUPS, 3)
        _wait_until(lambda: not controller.busy)
        settings.reset_device(COMPUTE_SOUND_CHECK)
        _wait_until(lambda: not controller.busy)
        assert settings.get(COMPUTE_SOUND_CHECK) is True
        assert settings.get(MAX_BACKUPS) == 3
        first_active = controller.active_ipod
        assert first_active is not None
        controller.select_device(candidates[1].id.value)
        _wait_until(lambda: not controller.busy)
        assert settings.get(MAX_BACKUPS) == 0
        with pytest.raises(DeviceChangedError):
            coordinator.save_settings(first_active, first_active.settings, {})
        controller.select_device(candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        assert settings.get(MAX_BACKUPS) == 3
        platform.disconnect(first)
        platform.disconnect(second)
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        assert not settings.device_connected
        assert settings.get(MAX_BACKUPS) == 0
    finally:
        controller.shutdown()
    documents = [
        json.loads(path.read_bytes()) for path in tmp_path.rglob("settings-v2.json")
    ]
    assert documents == [{"version": 1, "overrides": {MAX_BACKUPS.key: 3}}]


@pytest.mark.parametrize("state", ["read-only", "disconnected"])
def test_unavailable_ipod_never_receives_settings_or_leaks_overrides(
    tmp_path: Path, state: str
) -> None:
    root = _device_root(tmp_path / "device")
    path = root / str(SETTINGS_PATH)
    path.parent.mkdir(parents=True)
    original = b'{"version":1,"overrides":{"backups/max-per-device":10}}'
    path.write_bytes(original)
    platform = VirtualStoragePlatform()
    platform.add_volume(root, writable=state != "read-only")
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)), TrackTableModel(), settings
    )
    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        assert settings.get(MAX_BACKUPS) == 10
        if state == "read-only":
            assert not settings.device_writable
            with pytest.raises(RuntimeError):
                settings.set_device(MAX_BACKUPS, 3)
        else:
            platform.disconnect(root)
            settings.set_device(MAX_BACKUPS, 3)
            _wait_until(lambda: not controller.busy)
            assert not settings.device_connected
            assert controller.active_ipod is None
            assert settings.get(MAX_BACKUPS) == 0
            assert settings.device_message
        assert path.read_bytes() == original
    finally:
        controller.shutdown()


def test_external_change_rejects_save_and_leaves_host_values_untouched(
    tmp_path: Path,
) -> None:
    root = _device_root(tmp_path / "device")
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)), TrackTableModel(), settings
    )
    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        path = root / str(SETTINGS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        external = b'{"version":1,"overrides":{"backups/max-per-device":20}}'
        path.write_bytes(external)
        settings.set_device(MAX_BACKUPS, 5)
        _wait_until(lambda: not controller.busy)
        assert not settings.device_writable
        assert "could not be saved" in settings.device_message
        assert settings.get(MAX_BACKUPS) == settings.get_global(MAX_BACKUPS) == 0
        assert path.read_bytes() == external
        assert controller.reload_active_ipod()
        _wait_until(lambda: not controller.busy)
        assert settings.get(MAX_BACKUPS) == 20 and settings.device_writable
    finally:
        controller.shutdown()
