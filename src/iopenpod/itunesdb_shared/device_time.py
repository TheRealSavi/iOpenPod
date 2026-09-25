"""Device-clock conversion at the iPod binary-format boundary.

The classic iPod stores many date fields as unsigned 32-bit seconds since
1904-01-01 *in the device's local wall clock*.  Application code uses Unix
UTC seconds.  Keeping the conversion in one explicit context prevents the
host computer's timezone from leaking into device data.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAC_EPOCH_OFFSET = 2_082_844_800
MAC_EPOCH = datetime(1904, 1, 1)
MAC_U32_MAX = 0xFFFF_FFFF


class MacTimestampOutOfRangeError(ValueError):
    """A UTC instant cannot be represented by an iPod's u32 Mac timestamp."""


# These are the city-code values used by the 2,952/2,956/2,960-byte
# Device/Preferences layouts.  They map to IANA (or equivalent POSIX) zone
# names; city labels themselves are deliberately not used in application data.
_CITY_TIMEZONE_NAMES: dict[int, str] = {
    0x01: "PST8PDT", 0x02: "America/Chicago", 0x03: "Pacific/Honolulu",
    0x04: "America/Anchorage", 0x05: "PST8PDT", 0x06: "America/Los_Angeles",
    0x07: "PST8PDT", 0x08: "PST8PDT", 0x09: "PST8PDT", 0x0A: "PST8PDT",
    0x0B: "America/Vancouver", 0x0C: "MST7MDT", 0x0D: "America/Denver",
    0x0E: "America/Phoenix", 0x0F: "MST7MDT", 0x10: "CST6CDT",
    0x11: "CST6CDT", 0x12: "America/Guatemala", 0x13: "America/Managua",
    0x14: "CST6CDT", 0x15: "America/Mexico_City", 0x16: "CST6CDT",
    0x17: "America/Regina", 0x18: "PST8PDT", 0x19: "America/El_Salvador",
    0x1A: "CST6CDT", 0x1B: "America/Tegucigalpa", 0x1C: "America/Winnipeg",
    0x1D: "EST5EDT", 0x1E: "America/Bogota", 0x1F: "EST5EDT",
    0x20: "EST5EDT", 0x21: "America/Detroit", 0x22: "America/Havana",
    0x23: "America/Indiana/Indianapolis", 0x24: "EST5EDT", 0x25: "America/Lima",
    0x26: "Europe/London", 0x27: "EST5EDT", 0x28: "America/Montreal",
    0x29: "America/New_York", 0x2A: "EST5EDT", 0x2B: "America/Panama",
    0x2C: "EST5EDT", 0x2D: "America/Port-au-Prince", 0x2E: "America/Guayaquil",
    0x2F: "America/Toronto", 0x30: "EST5EDT", 0x31: "America/Asuncion",
    0x32: "America/Caracas", 0x33: "America/Guyana", 0x34: "America/Halifax",
    0x35: "America/La_Paz", 0x36: "America/Argentina/San_Juan",
    0x37: "America/Santiago", 0x38: "America/Santo_Domingo",
    0x39: "America/St_Johns", 0x3A: "America/Sao_Paulo",
    0x3B: "America/Argentina/Buenos_Aires", 0x3C: "America/Cayenne",
    0x3D: "America/Montevideo", 0x3E: "America/Godthab",
    0x3F: "America/Paramaribo", 0x40: "America/Recife",
    0x41: "Africa/Casablanca", 0x42: "America/Sao_Paulo",
    0x43: "Atlantic/South_Georgia", 0x44: "Atlantic/Azores",
    0x45: "Europe/Dublin", 0x46: "Africa/Accra", 0x47: "Africa/Bamako",
    0x48: "Europe/London", 0x49: "Africa/Conakry", 0x4A: "Africa/Dakar",
    0x4B: "Europe/Dublin", 0x4C: "Europe/London", 0x4D: "Africa/Freetown",
    0x4E: "Europe/Lisbon", 0x4F: "Europe/London", 0x50: "Africa/Monrovia",
    0x51: "Africa/Nouakchott", 0x52: "Africa/Ouagadougou",
    0x53: "Atlantic/Reykjavik", 0x54: "Africa/Algiers", 0x55: "Europe/Amsterdam",
    0x56: "Africa/Bangui", 0x57: "Europe/Belgrade", 0x58: "Europe/Berlin",
    0x59: "Europe/Brussels", 0x5A: "Europe/Budapest", 0x5B: "Europe/Copenhagen",
    0x5C: "Africa/Douala", 0x5D: "Europe/Paris", 0x5E: "Africa/Kinshasa",
    0x5F: "Africa/Lagos", 0x60: "Europe/Paris", 0x61: "Africa/Luanda",
    0x62: "Europe/Madrid", 0x63: "Europe/Berlin", 0x64: "Africa/Ndjamena",
    0x65: "Europe/Oslo", 0x66: "Europe/Paris", 0x67: "Europe/Prague",
    0x68: "Africa/Casablanca", 0x69: "Europe/Rome", 0x6A: "Europe/Stockholm",
    0x6B: "Africa/Tripoli", 0x6C: "Africa/Tunis", 0x6D: "Europe/Vienna",
    0x6E: "Europe/Warsaw", 0x6F: "Europe/Paris", 0x70: "Europe/Zurich",
    0x71: "Asia/Amman", 0x72: "EET", 0x73: "Asia/Beirut",
    0x74: "Europe/Bucharest", 0x75: "Africa/Cairo", 0x76: "Africa/Johannesburg",
    0x77: "Africa/Harare", 0x78: "Europe/Helsinki", 0x79: "Europe/Istanbul",
    0x7A: "Asia/Jerusalem", 0x7B: "Africa/Khartoum", 0x7C: "Europe/Kiev",
    0x7D: "Africa/Lusaka", 0x7E: "Africa/Maputo", 0x7F: "Europe/Sofia",
    0x80: "Africa/Addis_Ababa", 0x81: "Indian/Antananarivo",
    0x82: "Africa/Asmara", 0x83: "Asia/Baghdad", 0x84: "Asia/Damascus",
    0x85: "Africa/Dar_es_Salaam", 0x86: "Africa/Djibouti", 0x87: "Asia/Qatar",
    0x88: "Africa/Kampala", 0x89: "Asia/Bahrain", 0x8A: "Asia/Riyadh",
    0x8B: "Africa/Mogadishu", 0x8C: "Europe/Moscow", 0x8D: "Africa/Nairobi",
    0x8E: "Asia/Riyadh", 0x8F: "Asia/Aden", 0x90: "Europe/Moscow",
    0x91: "Europe/Volgograd", 0x92: "Asia/Dubai", 0x93: "Asia/Muscat",
    0x94: "Indian/Mauritius", 0x96: "Asia/Karachi", 0x97: "Indian/Maldives",
    0x98: "Asia/Samarkand", 0x99: "Asia/Yekaterinburg", 0x9A: "Asia/Omsk",
    0x9B: "Asia/Dhaka", 0x9C: "Asia/Novosibirsk", 0x9D: "Asia/Shanghai",
    0x9E: "Asia/Shanghai", 0x9F: "Asia/Hong_Kong", 0xA0: "Asia/Kuala_Lumpur",
    0xA1: "Asia/Manila", 0xA2: "Australia/Perth", 0xA3: "Asia/Shanghai",
    0xA4: "Asia/Singapore", 0xA5: "Asia/Taipei", 0xA6: "Asia/Shanghai",
    0xA7: "Asia/Ulaanbaatar", 0xA8: "Australia/Darwin", 0xA9: "Australia/Adelaide",
    0xAA: "Australia/Brisbane", 0xAB: "Australia/Melbourne",
    0xAC: "Pacific/Guam", 0xAD: "Australia/Hobart", 0xAE: "Australia/Melbourne",
    0xAF: "Australia/Melbourne", 0xB0: "Asia/Vladivostok", 0xB1: "Asia/Magadan",
    0xB2: "Pacific/Noumea", 0xB3: "Asia/Anadyr", 0xB4: "Pacific/Auckland",
    0xB5: "America/Adak", 0xB6: "Pacific/Pago_Pago", 0xB7: "Asia/Tehran",
    0xB8: "Asia/Kabul", 0xB9: "Asia/Kolkata", 0xBA: "Asia/Colombo",
    0xBB: "Asia/Kolkata", 0xBC: "Asia/Kolkata", 0xBD: "Asia/Kolkata",
    0xBE: "Asia/Kathmandu", 0xBF: "Asia/Tokyo", 0xC0: "Asia/Pyongyang",
    0xC1: "Asia/Seoul", 0xC2: "Asia/Tokyo", 0xC3: "Asia/Yakutsk",
    0xC4: "Europe/Athens", 0xC5: "Asia/Rangoon", 0xC6: "Asia/Ho_Chi_Minh",
    0xC7: "CST6CDT", 0xC8: "Asia/Bangkok", 0xC9: "Asia/Ho_Chi_Minh",
    0xCA: "Asia/Jakarta", 0xCB: "Asia/Krasnoyarsk", 0xCC: "Asia/Kuwait",
    0xCD: "Asia/Phnom_Penh",
}

_ZONE_ALIASES = {
    "PST8PDT": "America/Los_Angeles",
    "MST7MDT": "America/Denver",
    "CST6CDT": "America/Chicago",
    "EST5EDT": "America/New_York",
    "EET": "Europe/Athens",
}


@dataclass(frozen=True, slots=True)
class DeviceTimeContext:
    """The timezone used at an iPod binary timestamp boundary."""

    timezone: tzinfo
    name: str
    source: str
    city_id: int | None = None

    @classmethod
    def utc(cls) -> DeviceTimeContext:
        return cls(UTC, "UTC", "utc")

    @classmethod
    def fixed_offset(cls, seconds: int, *, source: str = "database_header") -> DeviceTimeContext:
        if not -24 * 60 * 60 <= seconds <= 24 * 60 * 60:
            raise ValueError(f"invalid UTC offset: {seconds}")
        return cls(timezone(timedelta(seconds=seconds)), f"UTC{seconds:+d}", source)

    @classmethod
    def from_timezone_name(
        cls,
        timezone_name: str,
        *,
        source: str = "device_preferences",
        city_id: int | None = None,
    ) -> DeviceTimeContext:
        canonical_name = _ZONE_ALIASES.get(timezone_name, timezone_name)
        try:
            zone = ZoneInfo(canonical_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown device timezone {timezone_name!r}") from exc
        return cls(zone, canonical_name, source, city_id)

    def offset_at_unix(self, unix_timestamp: int) -> int:
        instant = datetime.fromtimestamp(int(unix_timestamp), UTC)
        offset = instant.astimezone(self.timezone).utcoffset()
        return int(offset.total_seconds()) if offset else 0

    def mac_to_unix(self, mac_timestamp: int) -> int:
        if mac_timestamp <= 0:
            return 0
        local_wall_time = MAC_EPOCH + timedelta(seconds=int(mac_timestamp))
        return int(local_wall_time.replace(tzinfo=self.timezone).timestamp())

    def unix_to_mac(self, unix_timestamp: int) -> int:
        unix_timestamp = int(unix_timestamp or 0)
        if unix_timestamp <= 0:
            return 0
        local_wall_time = datetime.fromtimestamp(
            unix_timestamp, UTC,
        ).astimezone(self.timezone).replace(tzinfo=None)
        mac_timestamp = int((local_wall_time - MAC_EPOCH).total_seconds())
        if not 0 < mac_timestamp <= MAC_U32_MAX:
            raise MacTimestampOutOfRangeError(
                "iPod u32 Mac timestamps end at local 2040-02-06 06:28:15; "
                f"cannot encode {unix_timestamp} in {self.name}"
            )
        return mac_timestamp


_active_context: ContextVar[DeviceTimeContext | None] = ContextVar(
    "iopenpod_device_time_context", default=None,
)


def current_device_time_context() -> DeviceTimeContext:
    """Return the active conversion context, defaulting to UTC for APIs."""
    return _active_context.get() or DeviceTimeContext.utc()


def active_device_time_context() -> DeviceTimeContext | None:
    """Return the context configured by the current parser/writer boundary."""
    return _active_context.get()


@contextmanager
def use_device_time_context(context: DeviceTimeContext) -> Iterator[None]:
    """Apply one device clock context to nested parser/writer operations."""
    token = _active_context.set(context)
    try:
        yield
    finally:
        _active_context.reset(token)


def read_device_time_context(
    ipod_root: str | Path,
    *,
    database_offset: int | None = None,
) -> DeviceTimeContext:
    """Read the current device timezone, with the DB header as a fallback."""
    preferences = Path(ipod_root) / "iPod_Control" / "Device" / "Preferences"
    try:
        data = preferences.read_bytes()
    except OSError:
        data = b""

    if len(data) == 2892 and len(data) >= 0xB12:
        raw_timezone_4g = struct.unpack_from("<h", data, 0xB10)[0]
        if 0 <= raw_timezone_4g <= 48:
            return DeviceTimeContext.fixed_offset(
                ((raw_timezone_4g - 0x19) >> 1) * 3600
                + (3600 if raw_timezone_4g & 1 else 0),
                source="device_preferences",
            )
    elif len(data) == 2924 and len(data) >= 0xB24:
        raw_timezone_5g = struct.unpack_from("<h", data, 0xB22)[0]
        return DeviceTimeContext.fixed_offset(
            raw_timezone_5g * 60 - 8 * 3600, source="device_preferences",
        )
    elif len(data) in {2952, 2956, 2960} and len(data) >= 0xB72:
        city_id = struct.unpack_from("<H", data, 0xB70)[0]
        timezone_name = _CITY_TIMEZONE_NAMES.get(city_id)
        if timezone_name:
            return DeviceTimeContext.from_timezone_name(
                timezone_name, city_id=city_id,
            )

    if database_offset is not None:
        return DeviceTimeContext.fixed_offset(database_offset)
    return DeviceTimeContext.utc()


def timezone_changed_since_database(
    context: DeviceTimeContext,
    database_offset: int | None,
    *,
    now: int | None = None,
) -> bool:
    """Whether the current device clock differs from its last DB write zone."""
    if database_offset is None or context.source != "device_preferences":
        return False
    return context.offset_at_unix(int(time.time()) if now is None else now) != database_offset
