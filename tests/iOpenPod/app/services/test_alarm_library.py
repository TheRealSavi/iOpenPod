"""Library changes leave saved alarm selections untouched (ADR-0262)."""

import plistlib
from dataclasses import replace
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

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.alarms import parse_clock_alarms, update_clock_alarm, write_clock_alarms


@pytest.mark.parametrize(
    "model,release,updater,mini",
    (
        ("M9160", "1.4.1", 3, True),
        ("M9800", "1.4.1", 7, True),
        ("MA004", "1.3.1", 14, False),
        ("MA477", "1.1.3", 19, False),
        ("MA477", "1.1.3", 29, False),
        ("MA002", "1.3", 13, False),
    ),
)
@pytest.mark.parametrize("alarm_changed", (False, True))
def test_deleting_selected_playlist_does_not_rewrite_or_block_on_alarm(
    tmp_path: Path,
    model: str,
    release: str,
    updater: int,
    mini: bool,
    alarm_changed: bool,
) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model}\n", encoding="utf-8")
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": release, "UpdaterFamilyID": updater})
    )
    alarm_path = device / ("Preferences" if mini else "clock")
    original = (
        mini_alarm_source(playlist=20)
        if mini
        else write_clock_alarms(
            update_clock_alarm(parse_clock_alarms(GOLDEN), 0, sound_playlist_index=1)
        )
    )
    alarm_path.write_bytes(original)
    database = tmp_path / "iPod_Control/iTunes/iTunesDB"
    database.parent.mkdir()
    source = playlist_library(
        track_dataset(),
        playlist_dataset(
            2,
            (
                playlist_chunk(10, master=1),
                playlist_chunk(20, smart=True),
                playlist_chunk(30, smart=True),
            ),
        ),
    )
    database.write_bytes(source.serialize().itunes)
    coordinator = DeviceCoordinator(virtual_storage(tmp_path))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        assert {row.playlist_id for row in active.library.playlists} == {20, 30}
        desired = replace(
            active.library,
            playlists=tuple(
                row for row in active.library.playlists if row.playlist_id != 20
            ),
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(desired, active, 1, 1, delete_omissions=True),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        expected = b"changed or malformed alarm" if alarm_changed else original
        alarm_path.write_bytes(expected)
        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert {row.playlist_id for row in saved.active.library.playlists} == {30}
        assert alarm_path.read_bytes() == expected
        assert database.read_bytes() != source.serialize().itunes
    finally:
        coordinator.close()
