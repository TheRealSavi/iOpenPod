"""Native tone names and language evidence bind explicit sound choices."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import (
    virtual_storage,
    write_classic_language,
)
from tests.iOpenPod.app.services.test_alarm_service import CLASSIC
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk
from whenever import PlainDateTime

from iOpenPod.app.models.extras import CreateAlarm
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.alarms import parse_alarms
from storage import AccessMode, StorageError


def test_read_only_classic_still_reads_saved_alarm(tmp_path: Path) -> None:
    from tests.iPodDB.test_alarms import GOLDEN

    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    (device / "alarms").write_bytes(GOLDEN)
    storage = virtual_storage(tmp_path)
    with storage.open_session(storage.discover().volumes[0]) as session:
        catalog = read_extras(
            session, replace(CLASSIC, alarm_write=False), lambda: None
        )
    assert len(catalog.alarms) == 1 and not catalog.alarms[0].editable


def test_localized_beep_and_custom_contents_not_filenames(tmp_path: Path) -> None:
    write_classic_language(tmp_path, 3)
    tones = tmp_path / "iPod_Control/Tones"
    tones.mkdir()
    (tones / "unrelated.dat").write_bytes(b"Morning bells\n540 200\n")
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
        assert [sound.tone_name for sound in catalog.alarm_sounds] == [
            "Signalton",
            "Morning bells",
        ]
        for choice in catalog.alarm_sounds:
            transaction = prepare_change(
                catalog,
                CreateAlarm(PlainDateTime(2027, 1, 1), sound=choice),
                checkpoint=lambda: None,
            )
            assert transaction is not None
            data = transaction.writes[0].source
            assert isinstance(data, bytes)
            assert parse_alarms(data).records[0].tone_name == choice.tone_name
        with pytest.raises(ValueError, match="verified sound"):
            prepare_change(
                catalog, CreateAlarm(PlainDateTime(2027, 1, 1)), checkpoint=lambda: None
            )


@pytest.mark.parametrize("problem", ("missing_language", "duplicate", "too_many"))
def test_ambiguous_catalogs_never_guess_a_tone(tmp_path: Path, problem: str) -> None:
    if problem != "missing_language":
        write_classic_language(tmp_path)
        tones = tmp_path / "iPod_Control/Tones"
        tones.mkdir()
        for index in range(20 if problem == "too_many" else 2):
            (tones / str(index)).write_bytes(b"Same name\n540 200\n")
    storage = virtual_storage(tmp_path)
    with storage.open_session(storage.discover().volumes[0]) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
        assert len(catalog.alarm_sounds) == (0 if problem == "missing_language" else 1)
        assert catalog.can_create_alarm is (problem != "missing_language")
        assert catalog.issues


@pytest.mark.parametrize("stale", ("language", "tone", "inventory"))
def test_coordinator_rejects_changed_tone_evidence(tmp_path: Path, stale: str) -> None:
    write_classic_language(tmp_path)
    device = tmp_path / "iPod_Control/Device"
    (device / "SysInfo").write_text("ModelNumStr: MB565\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": "2.0.1", "UpdaterFamilyID": 33})
    )
    database = tmp_path / "iPod_Control/iTunes/iTunesDB"
    database.parent.mkdir()
    database.write_bytes(itunes_database(dataset(1, list_chunk(b"mhlt"))))
    tones = tmp_path / "iPod_Control/Tones"
    tones.mkdir()
    tone = tones / "one"
    tone.write_bytes(b"Morning\n540 200\n")
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        assert len(catalog.alarm_sounds) == 2
        change = CreateAlarm(PlainDateTime(2027, 1, 1), sound=catalog.alarm_sounds[1])
        if stale == "language":
            write_classic_language(tmp_path, 3)
        elif stale == "tone":
            tone.write_bytes(b"Evening\n540 200\n")
        else:
            (tones / "two").write_bytes(b"Other\n540 200\n")
        with pytest.raises((DeviceChangedError, StorageError)):
            coordinator.save_extras(active, catalog, change, Event())
        assert not (device / "alarms").exists()
    finally:
        coordinator.close()
