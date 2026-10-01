"""Known Preferences fields; offsets are shared by reader and writer.

Preferences is a flat firmware file, not an iTunesDB Chunk tree. See
docs/research/ipod-preferences.md for the evidence and model limitations.
"""

from dataclasses import dataclass
from enum import StrEnum

from iPodDB.shared.chunk import BinaryStruct
from iPodDB.shared.chunk_field import chunk_field as cf


class PreferencesLayout(StrEnum):
    UNKNOWN = "unknown"
    FOURTH_GENERATION = "fourth_generation"
    VIDEO = "video"
    CITY = "city"


class PreferencesProfile(StrEnum):
    """Caller assertions for fields whose meaning depends on model/firmware."""

    STANDARD = "standard"
    NANO_3 = "nano_3"
    VOLUME_LIMIT_1_1_1 = "volume_limit_1_1_1"


@dataclass(frozen=True, slots=True)
class FourthGenerationPreferences(BinaryStruct):
    """Language and the native zone/DST code in the 2,892-byte layout."""

    timezone_code: int = cf(0xB10, "i16")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class VideoPreferences(BinaryStruct):
    """Language and the minute-based zone code in the 2,924-byte layout."""

    timezone_code: int = cf(0xB22, "i16")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class CityPreferences(BinaryStruct):
    """Language and the two evidenced city bytes; adjacent bytes stay unknown."""

    city_id: int = cf(0xB70, "i16")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class Nano3Preferences(BinaryStruct):
    """Explicit DST switch; not an extra shift to apply to an IANA zone."""

    daylight_saving_minutes: int = cf(0x6BC, "u8")


@dataclass(frozen=True, slots=True)
class VolumeLimitPreferences(BinaryStruct):
    """Firmware 1.1.1 Video/nano setting, in device units 0 through 64."""

    volume_limit: int = cf(0xB50, "u8")


type ExtendedPreferencesSettings = Nano3Preferences | VolumeLimitPreferences


def extension_for_profile(
    profile: PreferencesProfile, size: int
) -> type[ExtendedPreferencesSettings] | None:
    if profile is PreferencesProfile.STANDARD:
        return None
    if profile is PreferencesProfile.NANO_3 and size == 2952:
        return Nano3Preferences
    if profile is PreferencesProfile.VOLUME_LIMIT_1_1_1 and size >= 2897:
        return VolumeLimitPreferences
    raise ValueError(f"Preferences profile {profile.value} does not fit {size} bytes.")


type PreferencesSettings = (
    FourthGenerationPreferences | VideoPreferences | CityPreferences
)


@dataclass(frozen=True, slots=True)
class PreferencesDefinition:
    layout: PreferencesLayout
    sizes: tuple[int, ...]
    settings_type: type[PreferencesSettings]


PREFERENCES_DEFINITIONS = (
    PreferencesDefinition(
        PreferencesLayout.FOURTH_GENERATION, (2892,), FourthGenerationPreferences
    ),
    PreferencesDefinition(PreferencesLayout.VIDEO, (2924,), VideoPreferences),
    PreferencesDefinition(PreferencesLayout.CITY, (2952, 2956, 2960), CityPreferences),
)


def definition_for_size(size: int) -> PreferencesDefinition | None:
    return next((item for item in PREFERENCES_DEFINITIONS if size in item.sizes), None)
