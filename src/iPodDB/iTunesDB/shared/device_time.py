"""Compatibility interface for captured fixed-offset Mac/Unix conversion."""

from whenever import Instant, TimeDelta

from iPodDB.device_time import (
    MAC_EPOCH_MAX as MAC_EPOCH_MAX,
)
from iPodDB.device_time import (
    MAC_EPOCH_UNIX_OFFSET as MAC_EPOCH_UNIX_OFFSET,
)
from iPodDB.device_time import (
    DeviceTimeContext,
    DeviceTimeSource,
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

UNIX_EPOCH = Instant.from_utc(1970, 1, 1)
MAC_EPOCH = Instant.from_utc(1904, 1, 1)


def _context(device_tz: TimeDelta) -> DeviceTimeContext:
    return DeviceTimeContext(device_tz, DeviceTimeSource.PREFERENCES_OFFSET)


def mac_to_unix(mac_seconds: int, device_tz: TimeDelta) -> int:
    return _decode(mac_seconds, _context(device_tz))


def unix_to_mac(unix_seconds: int, device_tz: TimeDelta) -> int:
    return _encode(unix_seconds, _context(device_tz))
