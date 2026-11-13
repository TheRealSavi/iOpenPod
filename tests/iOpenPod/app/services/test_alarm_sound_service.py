"""Sound selection is bound to native Library indices and captured source bytes."""

import plistlib
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.alarm_test_support import virtual_storage
from tests.iPodDB.alarm_fixtures import (
    mini_alarm_source,
    playlist_chunk,
    playlist_dataset,
    playlist_library,
    track_dataset,
)
from tests.iPodDB.test_clock_alarms import GOLDEN

from device_registry import AlarmFormat, ExtrasSupport, FirmwareTarget
from iOpenPod.app.models.extras import AlarmSound, SaveAlarm
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.alarms import (
    parse_clock_alarms,
    parse_preferences_alarm,
    update_clock_alarm,
    write_clock_alarms,
)
from iPodDB.library import AlarmPlaylistLayout
from storage import AccessMode, StorageError


@pytest.mark.parametrize(
    "mini,firmware",
    ((False, None), (True, None), (False, FirmwareTarget.NANO_2_1_1_3)),
)
def test_sound_selection_preserves_explicit_disabled_state(
    tmp_path: Path,
    mini: bool,
    firmware: FirmwareTarget | None,
) -> None:
    library = playlist_library(
        track_dataset(),
        playlist_dataset(
            2, (playlist_chunk(10, master=1), playlist_chunk(20, smart=True))
        ),
    )
    playlists = library.alarm_playlists(
        AlarmPlaylistLayout.MINI if mini else AlarmPlaylistLayout.CLOCK
    )
    path = tmp_path / "iPod_Control/Device" / ("Preferences" if mini else "clock")
    path.parent.mkdir(parents=True)
    path.write_bytes(mini_alarm_source(playlist=10) if mini else GOLDEN)
    support = ExtrasSupport(
        alarm_format=AlarmFormat.MINI if mini else AlarmFormat.CLOCK,
        alarm_write=True,
        alarm_firmware=firmware,
    )
    storage = virtual_storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None, alarm_playlists=playlists)
        item = catalog.alarms[0]
        assert item.enabled_editable and item.time is not None
        sound = next(
            choice
            for choice in catalog.alarm_sounds
            if choice.kind is AlarmSound.Kind.PLAYLIST
        )
        transaction = prepare_change(
            catalog,
            SaveAlarm(item, item.time, enabled=False, sound=sound),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        if mini:
            saved = parse_preferences_alarm(path.read_bytes(), "mini")
            assert saved.playlist_id == 20 and saved.enabled is False
        else:
            clock = parse_clock_alarms(path.read_bytes()).records[0]
            assert (clock.sound_selector, clock.sound_mode, clock.kind) == (1, 4, 8)


@pytest.mark.parametrize("no_op", (False, True))
@pytest.mark.parametrize(
    "model,release,updater",
    (("MA002", "1.3", 13), ("MA477", "1.1.3", 19), ("MA477", "1.1.3", 29)),
)
def test_coordinator_rejects_library_changed_after_sound_choices(
    tmp_path: Path,
    no_op: bool,
    model: str,
    release: str,
    updater: int,
) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model}\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": release, "UpdaterFamilyID": updater})
    )
    clock_path = device / "clock"
    original = (
        write_clock_alarms(
            update_clock_alarm(parse_clock_alarms(GOLDEN), 0, sound_playlist_index=-1)
        )
        if no_op
        else GOLDEN
    )
    clock_path.write_bytes(original)
    database = tmp_path / "iPod_Control/iTunes/iTunesDB"
    database.parent.mkdir(parents=True)
    library = playlist_library(
        track_dataset(),
        playlist_dataset(
            2, (playlist_chunk(10, master=1), playlist_chunk(20, smart=True))
        ),
    )
    database.write_bytes(library.serialize().itunes)
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        assert catalog.playlist_source is not None
        item = catalog.alarms[0]
        assert item.time is not None
        sound = catalog.alarm_sounds[0] if no_op else catalog.alarm_sounds[1]
        database.write_bytes(database.read_bytes() + b"external")
        with pytest.raises((StorageError, DeviceChangedError)):
            coordinator.save_extras(
                active, catalog, SaveAlarm(item, item.time, sound=sound), Event()
            )
        assert clock_path.read_bytes() == original
    finally:
        coordinator.close()
