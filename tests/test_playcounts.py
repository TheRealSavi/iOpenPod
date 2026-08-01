from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from iopenpod.itunesdb_parser.playcounts import PlayCountEntry
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
