"""Immutable native Preferences plus an explicit, host-independent zone reading."""

from dataclasses import dataclass

from iPodDB.preferences.definitions import (
    CityPreferences,
    ExtendedPreferencesSettings,
    FourthGenerationPreferences,
    PreferencesLayout,
    PreferencesProfile,
    PreferencesSettings,
    VideoPreferences,
)
from iPodDB.preferences.timezones import CITY_TIMEZONE_NAMES, TIME_ZONE_ALIASES


@dataclass(frozen=True, slots=True)
class FixedOffsetTimezone:
    """Effective seconds east of UTC, already including the encoded DST shift.

    This is an offset observation, not a geographical zone or historical rule.
    """

    offset_seconds: int


@dataclass(frozen=True, slots=True)
class CityTimezone:
    """Device city identity and its known zone name, if any.

    Resolving historical UTC offsets requires a separate timezone-data policy.
    An unknown city must not be silently interpreted as UTC or Host local time.
    """

    city_id: int
    timezone_name: str | None


type PreferencesTimezone = FixedOffsetTimezone | CityTimezone


def read_timezone(settings: PreferencesSettings | None) -> PreferencesTimezone | None:
    """Project only evidenced zone values, without consulting the clock or Host."""

    if isinstance(settings, FourthGenerationPreferences):
        if not 0 <= settings.timezone_code <= 48:
            return None
        adjusted = settings.timezone_code - 25
        # libgpod checks parity AFTER subtracting the odd origin, not before.
        offset = ((adjusted >> 1) + (adjusted & 1)) * 3600
        return FixedOffsetTimezone(offset)
    if isinstance(settings, VideoPreferences):
        offset = settings.timezone_code * 60 - 8 * 3600
        return FixedOffsetTimezone(offset) if -43200 <= offset <= 43200 else None
    if isinstance(settings, CityPreferences):
        name = CITY_TIMEZONE_NAMES.get(settings.city_id)
        return CityTimezone(
            settings.city_id,
            TIME_ZONE_ALIASES.get(name, name) if name is not None else None,
        )
    return None


@dataclass(frozen=True, slots=True)
class PreferencesDocument:
    """Native fields over exact source bytes, including every unknown byte.

    Construct with parse_preferences; edit settings using dataclasses.replace.
    The retained source fixes the layout and extent used by write_preferences.
    UNKNOWN is an explicitly opaque document and has no editable settings.
    """

    source_bytes: bytes
    layout: PreferencesLayout
    settings: PreferencesSettings | None
    profile: PreferencesProfile = PreferencesProfile.STANDARD
    extended_settings: ExtendedPreferencesSettings | None = None

    @property
    def timezone(self) -> PreferencesTimezone | None:
        return read_timezone(self.settings)
