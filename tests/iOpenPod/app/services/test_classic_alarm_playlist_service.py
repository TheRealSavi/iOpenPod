"""Explicit Classic/Nano playlist choices round-trip their native selectors."""

import plistlib
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import (
    virtual_storage,
    write_classic_language,
)
from tests.iPodDB.alarm_fixtures import (
    named_playlist_chunk,
    nano5_sources,
    playlist_dataset,
    playlist_library,
    track_dataset,
)
from whenever import PlainDateTime

from iOpenPod.app.models.extras import AlarmSound, CreateAlarm, SaveAlarm
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iPodDB.alarms import parse_alarms
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from storage import StorageError

MODELS = (
    ("MB029", "1.1.2", 24),
    ("MB565", "2.0.1", 33),
    ("MC293", "2.0.4", 35),
    ("MC293", "2.0.5", 38),
    ("MA978", "1.1.3", 26),
    ("MB598", "1.0.4", 31),
    ("MC027", "1.0.2", 34),
)


@pytest.mark.parametrize("enabled", (True, False))
def test_explicit_tone_and_playlist_switch_preserves_enable_gate(
    tmp_path: Path, enabled: bool
) -> None:
    coordinator = _coordinator(tmp_path, *MODELS[1])
    write_classic_language(tmp_path)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        beep = next(
            sound
            for sound in catalog.alarm_sounds
            if sound.kind is AlarmSound.Kind.BEEP
        )
        playlist = next(
            sound
            for sound in catalog.alarm_sounds
            if sound.kind is AlarmSound.Kind.PLAYLIST
        )
        when = PlainDateTime(2027, 1, 1, 7)
        catalog = coordinator.save_extras(
            active, catalog, CreateAlarm(when, enabled=enabled, sound=beep), Event()
        )
        path = tmp_path / "iPod_Control/Device/alarms"
        for sound in (playlist, beep):
            catalog = coordinator.save_extras(
                active,
                catalog,
                SaveAlarm(catalog.alarms[0], when, sound=sound),
                Event(),
            )
            record = parse_alarms(path.read_bytes()).records[0]
            assert record.control_word == (8 if enabled else 0)
            assert record.tone_name == ("" if sound is playlist else "Beep")
            assert record.sound_selector == (0 if sound is playlist else 0xFFFFFFFF)
            assert catalog.alarms[0].sound == sound
    finally:
        coordinator.close()


def _coordinator(
    tmp_path: Path, model: str, release: str, updater: int
) -> DeviceCoordinator:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model}\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": release, "UpdaterFamilyID": updater})
    )
    database = (
        tmp_path
        / "iPod_Control/iTunes"
        / ("iTunesCDB" if updater == 34 else "iTunesDB")
    )
    database.parent.mkdir()
    data = (
        playlist_library(
            track_dataset(),
            playlist_dataset(
                3,
                (
                    named_playlist_chunk(100, "Library", master=True),
                    named_playlist_chunk(20, "Zebra"),
                    named_playlist_chunk(30, "Alpha"),
                ),
            ),
        )
        .serialize()
        .itunes
    )
    database.write_bytes(compress_iTunesCDB(data) if updater == 34 else data)
    if updater == 34:
        folder = database.parent / "iTunes Library.itlp"
        folder.mkdir()
        for name, data in zip(
            ("Library.itdb", "Dynamic.itdb"), nano5_sources(), strict=True
        ):
            (folder / name).write_bytes(data)
    return DeviceCoordinator(virtual_storage(tmp_path))


@pytest.mark.parametrize("model,release,updater", MODELS)
def test_create_read_change_disable_and_reload_playlist(
    tmp_path: Path, model: str, release: str, updater: int
) -> None:
    coordinator = _coordinator(tmp_path, model, release, updater)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        sounds = tuple(
            sound
            for sound in catalog.alarm_sounds
            if sound.kind is AlarmSound.Kind.PLAYLIST
        )
        assert [sound.name for sound in sounds] == (
            ["Zebra", "Alpha", "On-The-Go 1"] if updater == 34 else ["Alpha", "Zebra"]
        ), catalog.issues
        assert catalog.can_create_alarm
        catalog = coordinator.save_extras(
            active,
            catalog,
            CreateAlarm(PlainDateTime(2027, 1, 1, 7, 30), sound=sounds[0]),
            Event(),
        )
        assert catalog.alarms[0].sound == sounds[0]
        path = tmp_path / "iPod_Control/Device/alarms"
        record = parse_alarms(path.read_bytes()).records[0]
        assert (record.sound_selector, record.tone_name, record.control_word) == (
            0,
            "",
            4,
        )
        catalog = coordinator.save_extras(
            active,
            catalog,
            SaveAlarm(
                catalog.alarms[0],
                PlainDateTime(2027, 1, 1, 8),
                enabled=False,
                sound=sounds[1],
            ),
            Event(),
        )
        assert catalog.alarms[0].sound == sounds[1]
        assert catalog.alarms[0].enabled is False
        record = parse_alarms(path.read_bytes()).records[0]
        assert (record.sound_selector, record.tone_name, record.control_word) == (
            1,
            "",
            0,
        )
        assert not (tmp_path / "iPod_Control/Device/Preferences").exists()
    finally:
        coordinator.close()


@pytest.mark.parametrize("changed", ("binary", "Library.itdb", "Dynamic.itdb"))
def test_explicit_selection_rechecks_every_playlist_source(
    tmp_path: Path, changed: str
) -> None:
    nano = changed != "binary"
    coordinator = _coordinator(tmp_path, *(MODELS[-1] if nano else MODELS[1]))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        assert catalog.alarm_sounds, catalog.issues
        path = (
            tmp_path
            / "iPod_Control/iTunes"
            / (f"iTunes Library.itlp/{changed}" if nano else "iTunesDB")
        )
        path.write_bytes(path.read_bytes() + b"external")
        with pytest.raises((StorageError, DeviceChangedError)):
            coordinator.save_extras(
                active,
                catalog,
                CreateAlarm(PlainDateTime(2027, 1, 1), sound=catalog.alarm_sounds[0]),
                Event(),
            )
        assert not (tmp_path / "iPod_Control/Device/alarms").exists()
    finally:
        coordinator.close()
