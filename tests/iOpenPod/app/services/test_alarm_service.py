"""Alarm authoring publishes source-checked files through virtual Storage."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import (
    virtual_storage,
    write_classic_language,
)
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk
from tests.iPodDB.test_alarms import GOLDEN as CLASSIC_GOLDEN
from tests.iPodDB.test_clock_alarms import CITY, GOLDEN
from whenever import PlainDateTime, Time

from device_registry import AlarmFormat, ExtrasSupport, FirmwareTarget
from iOpenPod.app.models.extras import CreateAlarm, RemoveAlarm, SaveAlarm
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.alarms import parse_alarms, parse_clock_alarms
from storage import AccessMode, FilePreconditionError, StorageError

CLASSIC = ExtrasSupport(
    alarm_format=AlarmFormat.CLASSIC,
    alarm_write=True,
    alarm_firmware=FirmwareTarget.CLASSIC_120GB_2_0_1,
)


@pytest.mark.parametrize("operation", ("create", "edit", "remove"))
def test_every_alarm_intent_rechecks_firmware_before_publication(
    tmp_path: Path, operation: str
) -> None:
    device = tmp_path / "iPod_Control/Device"
    database = tmp_path / "iPod_Control/iTunes"
    device.mkdir(parents=True)
    database.mkdir(parents=True)
    (device / "SysInfo").write_text("ModelNumStr: MB565\n", encoding="utf-8")
    metadata = device / "SysInfoExtended"
    metadata.write_bytes(
        plistlib.dumps({"VisibleBuildID": "2.0.1", "UpdaterFamilyID": 33})
    )
    (database / "iTunesDB").write_bytes(
        itunes_database(dataset(1, list_chunk(b"mhlt")))
    )
    path = device / "alarms"
    path.write_bytes(CLASSIC_GOLDEN)
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        change = (
            CreateAlarm(PlainDateTime(2027, 1, 1))
            if operation == "create"
            else RemoveAlarm(catalog.alarms[0])
            if operation == "remove"
            else SaveAlarm(catalog.alarms[0], PlainDateTime(2027, 1, 1))
        )
        metadata.write_bytes(
            plistlib.dumps({"VisibleBuildID": "9.9.9", "UpdaterFamilyID": 999})
        )
        with pytest.raises(DeviceChangedError, match="firmware evidence changed"):
            coordinator.save_extras(active, catalog, change, Event())
        assert path.read_bytes() == CLASSIC_GOLDEN
        assert coordinator.active_ipod is active
    finally:
        coordinator.close()


def test_create_disable_and_remove_native_alarm_with_verified_publication(
    tmp_path: Path,
) -> None:
    write_classic_language(tmp_path)
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
        assert catalog.can_create_alarm and not catalog.alarms
        change = CreateAlarm(
            PlainDateTime(2026, 11, 20, 7, 30), 2, sound=catalog.alarm_sounds[0]
        )
        transaction = prepare_change(catalog, change, checkpoint=lambda: None)
        assert transaction is not None and transaction.writes[0].expected is None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        path = tmp_path / "iPod_Control/Device/alarms"
        created = path.read_bytes()
        alarm = parse_alarms(created).records[0]
        assert alarm.scheduled == change.time and alarm.repeat == 2 and alarm.enabled
        assert (
            alarm.control_word,
            alarm.selection,
            alarm.sound_selector,
            alarm.label,
        ) == (8, 3, 0xFFFFFFFF, "Beep")
        catalog = read_extras(session, CLASSIC, lambda: None)
        item = catalog.alarms[0]
        assert item.enabled and item.enabled_editable and item.time is not None
        transaction = prepare_change(
            catalog, SaveAlarm(item, item.time, enabled=False), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert parse_alarms(path.read_bytes()).records[0].enabled is False
        assert path.read_bytes()[:32] == created[:32]
        assert path.read_bytes()[36:] == created[36:]
        catalog = read_extras(session, CLASSIC, lambda: None)
        transaction = prepare_change(
            catalog, RemoveAlarm(catalog.alarms[0]), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert path.read_bytes() == bytes.fromhex("3a0000403a0000c0")
        assert read_extras(session, CLASSIC, lambda: None).can_create_alarm


def test_creation_rejects_external_file_and_malformed_existing_collection(
    tmp_path: Path,
) -> None:
    write_classic_language(tmp_path)
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
        transaction = prepare_change(
            catalog,
            CreateAlarm(PlainDateTime(2027, 1, 1), sound=catalog.alarm_sounds[0]),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        path = tmp_path / "iPod_Control/Device/alarms"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"external alarm bytes")
        with pytest.raises((FilePreconditionError, StorageError)):
            session.execute_transaction(transaction)
        catalog = read_extras(session, CLASSIC, lambda: None)
        assert not catalog.can_create_alarm and catalog.issues
        with pytest.raises(ValueError, match="Reload"):
            prepare_change(
                catalog, CreateAlarm(PlainDateTime(2027, 1, 1)), checkpoint=lambda: None
            )
        assert path.read_bytes() == b"external alarm bytes"


@pytest.mark.parametrize("firmware", (None, FirmwareTarget.NANO_2_1_1_3))
def test_per_city_edit_preserves_other_city_and_never_writes_preferences(
    tmp_path: Path,
    firmware: FirmwareTarget | None,
) -> None:
    path = tmp_path / "iPod_Control/Device/clock"
    path.parent.mkdir(parents=True)
    source = GOLDEN[:-4] + CITY + GOLDEN[-4:]
    path.write_bytes(source)
    preferences = path.with_name("Preferences")
    preferences.write_bytes(b"independent projection")
    support = ExtrasSupport(
        alarm_format=AlarmFormat.CLOCK, alarm_write=True, alarm_firmware=firmware
    )
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert len(catalog.alarms) == 2 and catalog.can_create_alarm
        assert all(item.display_label == "Dallas" for item in catalog.alarms)
        transaction = prepare_change(
            catalog, SaveAlarm(catalog.alarms[1], Time(9, 45)), checkpoint=lambda: None
        )
        assert transaction is not None
        path.write_bytes(source + b"external")
        with pytest.raises((FilePreconditionError, StorageError)):
            session.execute_transaction(transaction)
        path.write_bytes(source)
        catalog = read_extras(session, support, lambda: None)
        transaction = prepare_change(
            catalog, SaveAlarm(catalog.alarms[1], Time(9, 45)), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert path.read_bytes()[:129] == source[:129]
        assert [
            alarm.time for alarm in parse_clock_alarms(path.read_bytes()).records
        ] == [Time(8), Time(9, 45)]
        assert preferences.read_bytes() == b"independent projection"
        catalog = read_extras(session, support, lambda: None)
        removal = prepare_change(
            catalog, RemoveAlarm(catalog.alarms[1]), checkpoint=lambda: None
        )
        assert removal is not None
        result = session.execute_transaction(removal)
        session.finalize_transaction(result.recovery)
        assert path.read_bytes() == GOLDEN


@pytest.mark.parametrize(
    "firmware,separate",
    [
        (FirmwareTarget.NANO_6_1_2, True),
        (FirmwareTarget.NANO_7_1_0_4, False),
        (FirmwareTarget.NANO_UPDATER_39_1_1_2, False),
    ],
)
def test_timer_read_is_optional_and_never_authorizes_alarm_writes(
    tmp_path: Path, firmware: FirmwareTarget, separate: bool
) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    duration = b"<Hours>1</Hours><Minutes>15</Minutes>"
    action = b"<SleepiPod>1</SleepiPod><SoundIndex>2</SoundIndex><DateTime>20261113023000</DateTime>"

    def xml(body: bytes) -> bytes:
        return (
            b'<iPodSettings version="1.0"><Timer>' + body + b"</Timer></iPodSettings>"
        )

    settings = device / "iPodSettings.xml"
    settings.write_bytes(xml(duration if separate else duration + action))
    if separate:
        (device / "iPodTimerSettings.xml").write_bytes(xml(action))
    support = ExtrasSupport(alarm_format=AlarmFormat.TIMER, alarm_firmware=firmware)
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert (
            not catalog.alarms and not catalog.can_create_alarm and not catalog.issues
        )
        assert catalog.timer is not None
        assert (
            catalog.timer.saved_hours,
            catalog.timer.saved_minutes,
            catalog.timer.sleep_ipod,
        ) == (1, 15, True)
        assert catalog.timer.deadline == PlainDateTime(2026, 11, 13, 2, 30)
        with pytest.raises(ValueError, match="unavailable"):
            prepare_change(
                catalog, CreateAlarm(PlainDateTime(2027, 1, 1)), checkpoint=lambda: None
            )
        unknown = read_extras(
            session, replace(support, alarm_format=AlarmFormat.NONE), lambda: None
        )
        assert unknown.timer is None
