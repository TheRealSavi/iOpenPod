"""Saved timer edits are source-bound and leave the active deadline intact."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import virtual_storage
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk

from device_registry import AlarmFormat, ExtrasSupport, FirmwareTarget
from iOpenPod.app.models.extras import SaveTimerSettings
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import (
    prepare_change,
    read_extras,
    timer_preconditions,
)
from iPodDB.alarms import CountdownTimerChanges
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from storage import AccessMode, StorageError

_DURATION = b"<Hours>1</Hours><Minutes>15</Minutes>"
_ACTION = (
    b"<SleepiPod>1</SleepiPod><SoundIndex>2</SoundIndex>"
    b"<DateTime>20261113223000</DateTime><Future>untouched</Future>"
)


def _stores(root: Path, *, separate: bool) -> tuple[Path, Path]:
    device = root / "iPod_Control/Device"
    device.mkdir(parents=True, exist_ok=True)
    settings = device / "iPodSettings.xml"
    timer = device / "iPodTimerSettings.xml" if separate else settings

    def xml(body: bytes) -> bytes:
        return (
            b'<iPodSettings version="1.0"><Timer>' + body + b"</Timer></iPodSettings>"
        )

    settings.write_bytes(xml(_DURATION if separate else _DURATION + _ACTION))
    if separate:
        timer.write_bytes(xml(_ACTION))
    return settings, timer


@pytest.mark.parametrize(
    "firmware",
    (
        FirmwareTarget.NANO_6_1_2,
        FirmwareTarget.NANO_7_1_0_4,
        FirmwareTarget.NANO_UPDATER_39_1_1_2,
    ),
)
def test_duration_and_tone_publish_together_without_changing_deadline(
    tmp_path: Path, firmware: FirmwareTarget
) -> None:
    separate = firmware is FirmwareTarget.NANO_6_1_2
    settings, timer = _stores(tmp_path, separate=separate)
    settings_before, timer_before = settings.read_bytes(), timer.read_bytes()
    support = ExtrasSupport(
        alarm_format=AlarmFormat.TIMER,
        alarm_firmware=firmware,
        timer_settings_write=True,
    )
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert catalog.timer and catalog.timer.can_edit_sound
        transaction = prepare_change(
            catalog,
            SaveTimerSettings(CountdownTimerChanges(saved_minutes=20, sound_index=9)),
            dependencies=timer_preconditions(catalog),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        assert len(transaction.writes) == (2 if separate else 1)
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        duration_after = settings_before.replace(b"<Minutes>15", b"<Minutes>20")
        action_after = timer_before.replace(b"<SleepiPod>1", b"<SleepiPod>0").replace(
            b"<SoundIndex>2", b"<SoundIndex>9"
        )
        if separate:
            assert settings.read_bytes() == duration_after
            assert timer.read_bytes() == action_after
        else:
            assert timer.read_bytes() == action_after.replace(
                b"<Minutes>15", b"<Minutes>20"
            )
        updated = read_extras(session, support, lambda: None)
        assert updated.timer and updated.timer.sound_index == 9
        assert not updated.timer.sleep_ipod
        assert updated.timer.deadline == catalog.timer.deadline
        with pytest.raises(ValueError, match="unavailable"):
            prepare_change(
                replace(catalog, support=replace(support, timer_settings_write=False)),
                SaveTimerSettings(CountdownTimerChanges(sound_index=1)),
                checkpoint=lambda: None,
            )


@pytest.mark.parametrize("stale", ("ordinary", "timer", "firmware", "no_op"))
def test_timer_coordinator_rejects_stale_stores_and_firmware_before_publication(
    tmp_path: Path, stale: str
) -> None:
    settings, timer = _stores(tmp_path, separate=True)
    settings_before, timer_before = settings.read_bytes(), timer.read_bytes()
    device = settings.parent
    (device / "SysInfo").write_text("ModelNumStr: MC525\n", encoding="utf-8")
    metadata = device / "SysInfoExtended"
    metadata.write_bytes(
        plistlib.dumps({"VisibleBuildID": "1.2", "UpdaterFamilyID": 36})
    )
    database = tmp_path / "iPod_Control/iTunes"
    database.mkdir(parents=True)
    (database / "iTunesCDB").write_bytes(
        compress_iTunesCDB(itunes_database(dataset(1, list_chunk(b"mhlt"))))
    )
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        if stale == "firmware":
            metadata.write_bytes(
                plistlib.dumps({"VisibleBuildID": "9.9", "UpdaterFamilyID": 36})
            )
        elif stale == "ordinary":
            settings.write_bytes(settings_before + b"<!-- external -->")
        else:
            timer.write_bytes(timer_before + b"<!-- external -->")
        changed_settings, changed_timer = settings.read_bytes(), timer.read_bytes()
        change = SaveTimerSettings(
            CountdownTimerChanges()
            if stale == "no_op"
            else CountdownTimerChanges(saved_minutes=20, sound_index=9)
        )
        with pytest.raises((DeviceChangedError, StorageError)):
            coordinator.save_extras(active, catalog, change, Event())
        assert settings.read_bytes() == changed_settings
        assert timer.read_bytes() == changed_timer
    finally:
        coordinator.close()
