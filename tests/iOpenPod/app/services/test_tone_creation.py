"""Explicit tone publication preserves alarms and checks its source collection."""

import plistlib
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import (
    virtual_storage,
    write_classic_language,
)
from tests.iOpenPod.app.services.test_alarm_service import CLASSIC
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk

from iOpenPod.app.models.extras import CreateTone
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.alarms import AlarmToneNote, parse_alarm_tone
from storage import AccessMode, StorageError

_NOTES = (AlarmToneNote(262, 500), AlarmToneNote(0, 100), AlarmToneNote(330, 500))


def _coordinator(root: Path) -> DeviceCoordinator:
    write_classic_language(root)
    device = root / "iPod_Control/Device"
    (device / "SysInfo").write_text("ModelNumStr: MB565\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": "2.0.1", "UpdaterFamilyID": 33})
    )
    database = root / "iPod_Control/iTunes/iTunesDB"
    database.parent.mkdir()
    database.write_bytes(itunes_database(dataset(1, list_chunk(b"mhlt"))))
    return DeviceCoordinator(virtual_storage(root))


def test_coordinator_adds_tone_without_changing_alarm_or_library(
    tmp_path: Path,
) -> None:
    from tests.iPodDB.test_alarms import GOLDEN

    coordinator = _coordinator(tmp_path)
    alarm = tmp_path / "iPod_Control/Device/alarms"
    alarm.write_bytes(GOLDEN)
    database = tmp_path / "iPod_Control/iTunes/iTunesDB"
    original_db = database.read_bytes()
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        updated = coordinator.save_extras(
            active, catalog, CreateTone("Morning melody", _NOTES), Event()
        )
        assert [tone.name for tone in updated.tones] == ["Beep", "Morning melody"]
        assert updated.tones[1].notes == _NOTES
        assert updated.alarm_sounds[-1].tone_name == "Morning melody"
        files = list((tmp_path / "iPod_Control/Tones").iterdir())
        assert len(files) == 1 and files[0].name.startswith("iopenpod-")
        assert parse_alarm_tone(files[0].read_bytes()).notes == _NOTES
        assert alarm.read_bytes() == GOLDEN and database.read_bytes() == original_db
    finally:
        coordinator.close()


@pytest.mark.parametrize("stale", ["language", "inventory", "firmware"])
def test_tone_creation_rejects_changed_sources(tmp_path: Path, stale: str) -> None:
    coordinator = _coordinator(tmp_path)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        if stale == "language":
            write_classic_language(tmp_path, 3)
        elif stale == "inventory":
            tones = tmp_path / "iPod_Control/Tones"
            tones.mkdir()
            (tones / "external.tone").write_bytes(b"External\n440 100\n")
        else:
            (tmp_path / "iPod_Control/Device/SysInfoExtended").write_bytes(
                plistlib.dumps({"VisibleBuildID": "9.9", "UpdaterFamilyID": 33})
            )
        with pytest.raises((DeviceChangedError, StorageError)):
            coordinator.save_extras(
                active, catalog, CreateTone("Morning", _NOTES), Event()
            )
        assert not list((tmp_path / "iPod_Control/Tones").glob("iopenpod-*"))
    finally:
        coordinator.close()


def test_native_capacity_and_names_do_not_author_ambiguous_tones(
    tmp_path: Path,
) -> None:
    write_classic_language(tmp_path)
    tones = tmp_path / "iPod_Control/Tones"
    tones.mkdir()
    (tones / "one").write_bytes(b"Morning\n440 100\n")
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
        for name in ("Morning", "Beep"):
            with pytest.raises(ValueError, match="name already exists"):
                prepare_change(
                    catalog, CreateTone(name, _NOTES), checkpoint=lambda: None
                )
        for index in range(18):
            (tones / f"{index}.tone").write_text(
                f"Tone {index}\n440 100\n", encoding="utf-8"
            )
        catalog = read_extras(session, CLASSIC, lambda: None)
        assert len(catalog.tones) == 20 and not catalog.can_create_tone
        with pytest.raises(ValueError, match="cannot be added"):
            prepare_change(
                catalog, CreateTone("Extra", _NOTES), checkpoint=lambda: None
            )


def test_missing_language_still_lists_captured_tones(tmp_path: Path) -> None:
    tones = tmp_path / "iPod_Control/Tones"
    tones.mkdir(parents=True)
    (tones / "one").write_bytes(b"Morning\n440 100\n")
    storage = virtual_storage(tmp_path)
    with storage.open_session(storage.discover().volumes[0]) as session:
        catalog = read_extras(session, CLASSIC, lambda: None)
    assert [tone.name for tone in catalog.tones] == ["Beep", "Morning"]
    assert not catalog.can_create_tone and not catalog.alarm_sounds
