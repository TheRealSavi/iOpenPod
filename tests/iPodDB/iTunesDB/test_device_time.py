"""Regression tests for iPod device-clock conversions."""

from datetime import timedelta, timezone

from iPodDB.iTunesDB.shared.device_time import mac_to_unix, unix_to_mac


def test_device_local_mac_timestamp_round_trips_to_unix_time() -> None:
    device_timezone = timezone(timedelta(hours=-5))
    unix_timestamp = 1_704_085_200  # 2024-01-01 05:00:00 UTC / midnight UTC-05:00.

    mac_timestamp = unix_to_mac(unix_timestamp, device_timezone)

    assert mac_timestamp == 3_786_912_000
    assert mac_to_unix(mac_timestamp, device_timezone) == unix_timestamp
