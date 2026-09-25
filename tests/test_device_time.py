from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime
from io import BytesIO

import pytest

from iopenpod.itunesdb_parser import parse_itunesdb
from iopenpod.itunesdb_parser.playcounts import PlayCountEntry, merge_playcounts
from iopenpod.itunesdb_shared.device_time import (
    DeviceTimeContext,
    MacTimestampOutOfRangeError,
    read_device_time_context,
    timezone_changed_since_database,
    use_device_time_context,
)
from iopenpod.itunesdb_shared.extraction import extract_datasets
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sqlitedb_writer._helpers import CORE_DATA_EPOCH, unix_to_coredata


def test_captured_play_counts_timestamps_use_the_device_timezone() -> None:
    """Regression for the Classic trace recorded on 2026-08-01.

    The device wrote the first value while configured for Eastern time and the
    second after it was switched to Rome.  Treating both values as this Mac's
    Eastern time makes the second instant six hours late.
    """
    eastern = DeviceTimeContext.from_timezone_name("America/New_York")
    rome = DeviceTimeContext.from_timezone_name("Europe/Rome")

    assert eastern.mac_to_unix(3_868_409_882) == int(
        datetime(2026, 8, 1, 10, 18, 2, tzinfo=UTC).timestamp()
    )
    assert rome.mac_to_unix(3_868_431_743) == int(
        datetime(2026, 8, 1, 10, 22, 23, tzinfo=UTC).timestamp()
    )


def test_timestamp_context_round_trips_dst_dates() -> None:
    context = DeviceTimeContext.from_timezone_name("Europe/Rome")
    instant = int(datetime(2026, 7, 1, 7, 30, tzinfo=UTC).timestamp())

    assert context.mac_to_unix(context.unix_to_mac(instant)) == instant


def test_mac_timestamp_overflow_is_not_silently_clamped() -> None:
    context = DeviceTimeContext.utc()

    with pytest.raises(MacTimestampOutOfRangeError):
        context.unix_to_mac(2_212_122_496)


def test_classic_preferences_selects_rome_timezone(tmp_path) -> None:
    preferences = tmp_path / "iPod_Control" / "Device" / "Preferences"
    preferences.parent.mkdir(parents=True)
    raw = bytearray(2956)
    raw[0xB70:0xB72] = (0x69).to_bytes(2, "little")
    preferences.write_bytes(raw)

    context = read_device_time_context(tmp_path, database_offset=-14_400)

    assert context.name == "Europe/Rome"
    assert context.city_id == 0x69
    assert timezone_changed_since_database(
        context,
        -14_400,
        now=int(datetime(2026, 8, 1, 10, tzinfo=UTC).timestamp()),
    )


def test_classic_preferences_uses_bundled_timezone_data_when_system_data_is_missing(tmp_path) -> None:
    preferences = tmp_path / "iPod_Control" / "Device" / "Preferences"
    preferences.parent.mkdir(parents=True)
    raw = bytearray(2956)
    raw[0xB70:0xB72] = (0x29).to_bytes(2, "little")
    preferences.write_bytes(raw)

    zoneinfo.reset_tzpath(())
    try:
        context = read_device_time_context(tmp_path)
    finally:
        zoneinfo.reset_tzpath()

    assert context.name == "America/New_York"
    assert context.city_id == 0x29


def test_play_count_merge_never_uses_the_host_timezone() -> None:
    tracks = [{"play_count_1": 0, "last_played": 0}]
    entries = [PlayCountEntry(play_count=1, last_played_mac=3_868_431_743)]

    merge_playcounts(
        tracks,
        entries,
        time_context=DeviceTimeContext.from_timezone_name("Europe/Rome"),
    )

    assert tracks[0]["play_count_1"] == 1
    assert tracks[0]["last_played"] == int(
        datetime(2026, 8, 1, 10, 22, 23, tzinfo=UTC).timestamp()
    )


def test_core_data_dates_are_absolute_utc() -> None:
    instant = int(datetime(2026, 8, 1, 10, 22, 23, tzinfo=UTC).timestamp())

    assert unix_to_coredata(instant) == instant - CORE_DATA_EPOCH


def test_binary_itunesdb_dates_round_trip_through_device_context() -> None:
    context = DeviceTimeContext.from_timezone_name("Europe/Rome")
    instant = int(datetime(2026, 8, 1, 10, 22, 23, tzinfo=UTC).timestamp())
    track = TrackInfo(
        title="Timestamp trace",
        location=":iPod_Control:Music:F00:TIME.m4a",
        date_added=instant,
        last_modified=instant,
        last_played=instant,
        last_skipped=instant,
    )

    with use_device_time_context(context):
        data = write_mhbd([track])

    parsed = parse_itunesdb(BytesIO(data), time_context=context)
    parsed_track = extract_datasets(parsed)["mhlt"][0]

    assert parsed["timezone_offset"] == 7200
    assert {
        parsed_track["date_added"],
        parsed_track["last_modified"],
        parsed_track["last_played"],
        parsed_track["last_skipped"],
    } == {instant}
