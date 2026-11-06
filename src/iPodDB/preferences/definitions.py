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
    CLASSIC_6_1_1_2 = "classic_6_1_1_2"
    CLASSIC_120GB_2_0_1 = "classic_120gb_2_0_1"
    CLASSIC_UPDATER_35_2_0_4 = "classic_updater_35_2_0_4"
    CLASSIC_UPDATER_38_2_0_5 = "classic_updater_38_2_0_5"


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
class ClassicPreferences(BinaryStruct):
    """Qualified saved city and language; the full city word is retained.

    Firmware can reconcile the city after Host clock import, so this is not
    proof of a user's geographical selection or a historical event location.
    """

    city_id: int = cf(0xB70, "u32")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class Classic201Preferences(ClassicPreferences):
    """Qualified Classic fields; city is read-only and Alternate Audio stays raw.

    Alternate Audio uses 0 for Off and 1 for On, not a stream or language ID.
    Unknown byte values remain unchanged unless explicitly replaced with 0/1.
    """

    alternate_audio: int = cf(0xB85, "u8")


@dataclass(frozen=True, slots=True)
class ClassicClockPreferences(BinaryStruct):
    """Read-only saved clock state, distinct from a current or historical offset.

    DST callers store both 0/1 and 0/60. Saved Clock Correction is captured
    Preferences data; queued Host clock processing can refresh it later.
    Its seconds word is retained raw; neither it nor the day displacement
    establishes the Raw Hardware Clock's origin.
    """

    format_version: int = cf(0, "u32")
    retained_dst_state: int = cf(0xB6C, "u8")
    clock_bias_days: int = cf(0xB78, "i32")
    clock_bias_seconds: int = cf(0xB7C, "u32")


@dataclass(frozen=True, slots=True)
class Nano3Preferences(BinaryStruct):
    """Explicit DST switch; not an extra shift to apply to an IANA zone."""

    daylight_saving_minutes: int = cf(0x6BC, "u8")


@dataclass(frozen=True, slots=True)
class VolumeLimitPreferences(BinaryStruct):
    """Firmware 1.1.1 Video/nano setting, in device units 0 through 64."""

    volume_limit: int = cf(0xB50, "u8")


type ExtendedPreferencesSettings = (
    Nano3Preferences | VolumeLimitPreferences | ClassicClockPreferences
)


def extension_for_profile(
    profile: PreferencesProfile, size: int
) -> type[ExtendedPreferencesSettings] | None:
    if profile is PreferencesProfile.STANDARD:
        return None
    if profile is PreferencesProfile.NANO_3 and size == 2952:
        return Nano3Preferences
    if profile is PreferencesProfile.VOLUME_LIMIT_1_1_1 and size >= 2897:
        return VolumeLimitPreferences
    classic = CLASSIC_PREFERENCES_DEFINITIONS.get(profile)
    if classic is not None and size in classic.sizes:
        return ClassicClockPreferences
    raise ValueError(f"Preferences profile {profile.value} does not fit {size} bytes.")


type PreferencesSettings = (
    FourthGenerationPreferences
    | VideoPreferences
    | CityPreferences
    | ClassicPreferences
)


@dataclass(frozen=True, slots=True)
class PreferencesDefinition:
    layout: PreferencesLayout
    sizes: tuple[int, ...]
    settings_type: type[PreferencesSettings]
    format_version: int | None = None


CLASSIC_PREFERENCES_DEFINITIONS = {
    PreferencesProfile.CLASSIC_6_1_1_2: PreferencesDefinition(
        PreferencesLayout.CITY, (2952,), ClassicPreferences, 0x3C
    ),
    PreferencesProfile.CLASSIC_120GB_2_0_1: PreferencesDefinition(
        PreferencesLayout.CITY, (2956,), Classic201Preferences, 0x3D
    ),
    PreferencesProfile.CLASSIC_UPDATER_35_2_0_4: PreferencesDefinition(
        PreferencesLayout.CITY, (2956,), ClassicPreferences, 0x3E
    ),
    PreferencesProfile.CLASSIC_UPDATER_38_2_0_5: PreferencesDefinition(
        PreferencesLayout.CITY, (2960,), ClassicPreferences, 0x3F
    ),
}


PREFERENCES_DEFINITIONS = (
    PreferencesDefinition(
        PreferencesLayout.FOURTH_GENERATION, (2892,), FourthGenerationPreferences
    ),
    PreferencesDefinition(PreferencesLayout.VIDEO, (2924,), VideoPreferences),
    PreferencesDefinition(PreferencesLayout.CITY, (2952, 2956, 2960), CityPreferences),
)


def definition_for_size(
    size: int, profile: PreferencesProfile = PreferencesProfile.STANDARD
) -> PreferencesDefinition | None:
    classic = CLASSIC_PREFERENCES_DEFINITIONS.get(profile)
    if classic is not None:
        return classic if size in classic.sizes else None
    return next((item for item in PREFERENCES_DEFINITIONS if size in item.sizes), None)
