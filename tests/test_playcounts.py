from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from iopenpod.itunesdb_parser.playcounts import PlayCountEntry, merge_playcounts
from iopenpod.itunesdb_shared.device_time import DeviceTimeContext


def test_playcount_timestamp_uses_device_local_summer_time() -> None:
    """Play Counts timestamps use device, not host, timezone rules."""
    local_wall_time = datetime(2026, 7, 1, 9, 30)
    raw_mac_timestamp = int((local_wall_time - datetime(1904, 1, 1)).total_seconds())
    expected = int(local_wall_time.replace(tzinfo=ZoneInfo("Europe/Rome")).timestamp())

    entry = PlayCountEntry(
        last_played_mac=raw_mac_timestamp,
        last_skipped_mac=raw_mac_timestamp,
    )
    device_time = DeviceTimeContext.from_timezone_name("Europe/Rome")

    assert entry.last_played_as_unix(device_time) == expected
    assert entry.last_skipped_as_unix(device_time) == expected


def test_playcount_merge_accumulates_durable_pending_scrobbles() -> None:
    tracks = [{"play_count_1": 10, "play_count_2": 3}]

    merge_playcounts(tracks, [PlayCountEntry(play_count=2)])
    merge_playcounts(tracks, [PlayCountEntry(play_count=4)])

    assert tracks == [
        {
            "play_count_1": 16,
            "play_count_2": 9,
            "recent_playcount": 4,
            "recent_skipcount": 0,
            "skip_count": 0,
        }
    ]


def test_playcount_merge_preserves_pending_scrobbles_for_unmatched_track() -> None:
    tracks = [
        {"play_count_1": 10, "play_count_2": 3},
        {"play_count_1": 8, "play_count_2": 5},
    ]

    merge_playcounts(tracks, [PlayCountEntry(play_count=2)])

    assert tracks[0]["play_count_1"] == 12
    assert tracks[0]["play_count_2"] == 5
    assert tracks[1]["play_count_1"] == 8
    assert tracks[1]["play_count_2"] == 5
    assert tracks[1]["recent_playcount"] == 0
