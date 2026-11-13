"""City Alarm workflows use one source-checked Clock-file transaction."""

import plistlib
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import virtual_storage
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk
from tests.iPodDB.test_clock_alarms import GOLDEN
from whenever import Time

from iOpenPod.app.models.extras import CreateClockAlarm, RemoveAlarm, SaveAlarm
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.alarms import clock_city, empty_clock_document, parse_clock_alarms
from storage import StorageError


@pytest.mark.parametrize(
    "model,release,updater",
    (
        ("MA004", "1.3.1", 14),
        ("MA477", "1.1.3", 19),
        ("MA477", "1.1.3", 29),
        ("MA002", "1.3", 13),
        ("MA444", "1.3", 25),
    ),
)
@pytest.mark.parametrize("existing", (False, True))
def test_create_edit_and_remove_city_with_native_fields_and_source_checks(
    tmp_path: Path,
    model: str,
    release: str,
    updater: int,
    existing: bool,
) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model}\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": release, "UpdaterFamilyID": updater})
    )
    database = tmp_path / "iPod_Control/iTunes/iTunesDB"
    database.parent.mkdir()
    database.write_bytes(itunes_database(dataset(1, list_chunk(b"mhlt"))))
    path = device / "clock"
    if existing:
        path.write_bytes(GOLDEN)
    preferences = device / "Preferences"
    preferences.write_bytes(b"unrelated native projection")
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        assert catalog.can_create_alarm and len(catalog.clock_cities) == 204
        city = next(city for city in catalog.clock_cities if city.name == "Tokyo")
        change = CreateClockAlarm(
            city, Time(6, 45), True, True, catalog.alarm_sounds[0]
        )
        catalog = coordinator.save_extras(active, catalog, change, Event())
        assert catalog.alarms[-1].display_label == "Tokyo"
        record = parse_clock_alarms(path.read_bytes()).records[-1]
        assert clock_city(record.region, record.city) == city
        assert (
            record.minutes,
            record.daylight_saving,
            record.kind,
            record.selection,
            record.sound_selector,
        ) == (405, 1, 0, 0, 0xFFFFFFFF)
        if existing:
            assert path.read_bytes()[: len(GOLDEN) - 4] == GOLDEN[:-4]
        item = catalog.alarms[-1]
        catalog = coordinator.save_extras(
            active, catalog, SaveAlarm(item, Time(7), daylight_saving=False), Event()
        )
        assert catalog.alarms[-1].daylight_saving is False
        catalog = coordinator.save_extras(
            active, catalog, RemoveAlarm(catalog.alarms[-1]), Event()
        )
        assert path.read_bytes() == (
            GOLDEN if existing else empty_clock_document().source_bytes
        )
        before = path.read_bytes()
        path.write_bytes(before + b"changed")
        with pytest.raises(StorageError):
            coordinator.save_extras(active, catalog, change, Event())
        assert path.read_bytes() == before + b"changed"
        assert preferences.read_bytes() == b"unrelated native projection"
    finally:
        coordinator.close()
