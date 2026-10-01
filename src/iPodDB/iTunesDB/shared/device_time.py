"""Compatibility interface for captured fixed-offset Mac/Unix conversion."""

from datetime import UTC, datetime, timezone

from iPodDB.device_time import (
    MAC_EPOCH_MAX as MAC_EPOCH_MAX,
)
from iPodDB.device_time import (
    MAC_EPOCH_UNIX_OFFSET as MAC_EPOCH_UNIX_OFFSET,
)
from iPodDB.device_time import (
    MacTimestampOutOfRangeError as MacTimestampOutOfRangeError,
)
from iPodDB.device_time import (
    mac_to_unix as _decode,
)
from iPodDB.device_time import (
    unix_to_mac as _encode,
)
from iPodDB.preferences.timezones import CITY_TIMEZONE_NAMES as CITY_TIMEZONE_NAMES
from iPodDB.preferences.timezones import TIME_ZONE_ALIASES as TIME_ZONE_ALIASES

UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAC_EPOCH = datetime(1904, 1, 1, tzinfo=UTC)


def _offset(device_tz: object) -> int:
    if not isinstance(device_tz, timezone):
        raise TypeError("Device conversion requires a captured fixed-offset timezone.")
    offset = device_tz.utcoffset(None)
    return int(offset.total_seconds())


def mac_to_unix(mac_seconds: int, device_tz: timezone) -> int:
    return _decode(mac_seconds, _offset(device_tz))


def unix_to_mac(unix_seconds: int, device_tz: timezone) -> int:
    return _encode(unix_seconds, _offset(device_tz))
