"""Portable overrides retain absence, revisions, and connection safety."""

import json
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy

from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_MODE,
    COMPUTE_SOUND_CHECK,
    MAX_BACKUPS,
)
from iOpenPod.app.core.settings.device import (
    SETTINGS_PATH,
    DeviceSettings,
    load_device_settings,
    save_device_settings,
)
from iOpenPod.app.core.settings.service import SettingSource, SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from storage import AccessMode, Storage, StorageError
from storage.testing import VirtualStoragePlatform


def test_absent_false_zero_and_equal_overrides_remain_distinct() -> None:
    service = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    service.set_global(COMPUTE_SOUND_CHECK, True)
    service.set_global(MAX_BACKUPS, 5)
    service.load_device("one", {})
    service.set_device(COMPUTE_SOUND_CHECK, False)
    service.set_device(MAX_BACKUPS, 0)
    assert service.get(COMPUTE_SOUND_CHECK) is False
    assert service.get(MAX_BACKUPS) == 0
    assert service.get_global(MAX_BACKUPS) == 5
    service.set_global(MAX_BACKUPS, 0)
    assert service.source(MAX_BACKUPS) is SettingSource.DEVICE
    service.reset_device(MAX_BACKUPS)
    service.set_global(MAX_BACKUPS, 10)
    assert service.get(MAX_BACKUPS) == 10
    assert service.source(MAX_BACKUPS) is SettingSource.GLOBAL
    service.load_device("two", {})
    assert service.get(COMPUTE_SOUND_CHECK) is True
    assert service.get(MAX_BACKUPS) == 10
    service.unload_device()
    with pytest.raises(RuntimeError):
        service.reset_device(MAX_BACKUPS)


def test_runtime_consumers_receive_changes_on_switch_and_disconnect() -> None:
    service = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    assert service.get(MAX_BACKUPS) == 0
    changes = QSignalSpy(service.settingChanged)
    service.load_device("one", {MAX_BACKUPS.key: 10})
    service.load_device("two", {MAX_BACKUPS.key: 3})
    service.unload_device()
    assert [changes.at(i) for i in range(changes.count())] == [
        [MAX_BACKUPS.key, 10],
        [MAX_BACKUPS.key, 3],
        [MAX_BACKUPS.key, 0],
    ]


def test_invalid_or_host_only_overrides_do_not_affect_resolution() -> None:
    service = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    service.load_device("one", {MAX_BACKUPS.key: True, APPEARANCE_MODE.key: "dark"})
    assert service.get(MAX_BACKUPS) == 0
    assert service.get(APPEARANCE_MODE) == "system"
    with pytest.raises(ValueError):
        service.set_device(APPEARANCE_MODE, "dark")
    with pytest.raises(ValueError):
        service.reset_device(APPEARANCE_MODE)


def test_pending_or_failed_save_never_claims_the_requested_value() -> None:
    service = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    service.load_device("one", {}, managed=True)
    requested = QSignalSpy(service.deviceSaveRequested)
    service.set_device(MAX_BACKUPS, 3)
    assert service.device_busy and not service.device_writable
    assert service.get(MAX_BACKUPS) == 0
    assert requested.at(0) == [{MAX_BACKUPS.key: 3}]
    service.complete_device_save(None, "Disconnected")
    assert not service.device_busy
    assert service.device_message == "Disconnected"
    assert service.source(MAX_BACKUPS) is SettingSource.DEFAULT


def test_document_persistence_preserves_unknown_keys_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    mounted = storage.discover().volumes[0]
    with storage.open_session(mounted, access=AccessMode.READ_WRITE) as session:
        initial = load_device_settings(session)
        assert initial.writable and not session.exists(SETTINGS_PATH)
        saved = save_device_settings(
            session, initial, {MAX_BACKUPS.key: 0, "future/value": {"nested": 2}}
        )
        assert load_device_settings(session) == saved
        values = dict(saved.values)
        values.pop(MAX_BACKUPS.key)
        reset = save_device_settings(session, saved, values)
        assert dict(reset.values) == {"future/value": {"nested": 2}}
        with pytest.raises(StorageError):
            save_device_settings(session, saved, {MAX_BACKUPS.key: 10})
        assert load_device_settings(session) == reset


@pytest.mark.parametrize(
    "payload",
    [
        b"broken",
        b"[]",
        b'{"version":99,"overrides":{}}',
        b'{"version":1,"overrides":false}',
    ],
)
def test_unreadable_documents_are_preserved_and_cannot_be_replaced(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / str(SETTINGS_PATH)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        state = load_device_settings(session)
        assert not state.writable and state.message
        with pytest.raises(ValueError):
            save_device_settings(session, state, {})
    assert path.read_bytes() == payload


def test_saving_only_serializes_overrides(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        save_device_settings(
            session, DeviceSettings(writable=True), {MAX_BACKUPS.key: 3}
        )
    assert json.loads((tmp_path / str(SETTINGS_PATH)).read_bytes()) == {
        "version": 1,
        "overrides": {MAX_BACKUPS.key: 3},
    }
