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
    FIRMWARE = "firmware"


class PreferencesProfile(StrEnum):
    """Caller assertions for fields whose meaning depends on model/firmware."""

    STANDARD = "standard"
    MINI_1_1_4_1 = "mini_1_1_4_1"
    MINI_2_1_4_1 = "mini_2_1_4_1"
    NANO_1_1_3_1 = "nano_1_1_3_1"
    NANO_3_1_1_3 = "nano_3_1_1_3"
    NANO_4_1_0_4 = "nano_4_1_0_4"
    VIDEO_1_3 = "video_1_3"
    NANO_3 = "nano_3"
    VOLUME_LIMIT_1_1_1 = "volume_limit_1_1_1"
    CLASSIC_6_1_1_2 = "classic_6_1_1_2"
    CLASSIC_120GB_2_0_1 = "classic_120gb_2_0_1"
    CLASSIC_UPDATER_35_2_0_4 = "classic_updater_35_2_0_4"
    CLASSIC_UPDATER_38_2_0_5 = "classic_updater_38_2_0_5"


class NamedPreferencesProfile(StrEnum):
    """Explicit model/firmware assertions; never inferred from XML alone."""

    NANO_4_1_0_4 = "nano_4_1_0_4"
    NANO_5_1_0_2 = "nano_5_1_0_2"
    NANO_6_1_2 = "nano_6_1_2"
    NANO_7_1_0_4 = "nano_7_1_0_4"
    NANO_UPDATER_39_1_1_2 = "nano_updater_39_1_1_2"


class PreferenceKey(StrEnum):
    """Host-authorable settings whose firmware encoding is independently traced."""

    SHUFFLE_MODE = "shuffle_mode"
    REPEAT_MODE = "repeat_mode"
    EQ_PRESET = "eq_preset"
    SOUND_CHECK = "sound_check"
    BACKLIGHT_TIMEOUT = "backlight_timeout"
    BRIGHTNESS = "brightness"
    CLICKER = "clicker"
    ALTERNATE_AUDIO = "alternate_audio"
    AUDIOBOOK_SPEED = "audiobook_speed"
    CONTACT_SORT = "contact_sort"
    CONTACT_DISPLAY = "contact_display"
    PHOTO_DURATION = "photo_duration"
    PHOTO_REPEAT = "photo_repeat"
    PHOTO_SHUFFLE = "photo_shuffle"
    PHOTO_TRANSITION = "photo_transition"
    TV_OUT = "tv_out"
    TV_SIGNAL = "tv_signal"
    TV_SCREEN = "tv_screen"
    FIT_TO_SCREEN_DISABLED = "fit_to_screen_disabled"
    WIDESCREEN = "widescreen"
    VOICE_MEMO_QUALITY = "voice_memo_quality"
    NIKE_SPOKEN_FEEDBACK = "nike_spoken_feedback"
    NIKE_REMOTE_COMMANDS_DISABLED = "nike_remote_commands_disabled"


@dataclass(frozen=True, slots=True)
class PreferenceField:
    """An editable integer domain; display labels belong to the application.

    Values use saved native units except compound Shuffle (0 Off, 1 Songs,
    2 Albums) and Photo Transition (-1 Random, otherwise a profile-specific
    effect ID; legacy 0 means Off). Repeat uses native 0 Off, 1 All, 2 One.
    Clicker is its low two bits; upper bits survive. Backlight selectors are
    profile-specific, not seconds. Photo Duration uses actual seconds on the
    qualified modern profiles; legacy duration selectors remain read-only.
    Audiobook Speed is signed: -1 Slower, 0 Normal, 1 Faster. Inverted settings
    keep their native polarity, including Fit to Screen (0 On, 1 Off).
    An empty allowed_values tuple uses the inclusive minimum/maximum range.
    """

    key: PreferenceKey
    allowed_values: tuple[int, ...] = ()
    minimum: int | None = None
    maximum: int | None = None

    def accepts(self, value: int) -> bool:
        return type(value) is int and (
            value in self.allowed_values
            if self.allowed_values
            else self.minimum is not None
            and self.maximum is not None
            and self.minimum <= value <= self.maximum
        )


@dataclass(frozen=True, slots=True)
class FourthGenerationPreferences(BinaryStruct):
    """Language and the native zone/DST code in the 2,892-byte layout."""

    timezone_code: int = cf(0xB10, "i16")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class FirmwareLanguagePreferences(BinaryStruct):
    """Qualified language observation without an inferred clock layout.

    A recognized frame need not have a qualified timezone or language writer.
    The full native language word is retained; authoring its resource-dependent
    domain remains unsupported. Scalar settings use the separate native map.
    """

    language_code: int = cf(0xAF8, "u32")


@dataclass(frozen=True, slots=True)
class Mini2Preferences(BinaryStruct):
    """Latest Mini2 observations; selector 1..50 contains paired DST choices.

    Language is a native u32, unlike the older generic byte projection. Its
    resource-dependent language domain remains outside the authoring API.
    """

    timezone_selector: int = cf(0xB10, "u32")
    language_code: int = cf(0xAF8, "u32")


@dataclass(frozen=True, slots=True)
class Mini1Preferences(Mini2Preferences):
    """Mini 1 / 1.4.1: independently verified same selector and language map.

    The shared structure does not qualify a Mini 2 profile for a Mini 1 device.
    Both updater 3 and 6 execute all 50 selectors; their table encodes paired
    standard/DST fixed offsets, not geographical or historical timezone rules.
    """


PREFERENCES_ALARM_OFFSET = 0xB22


@dataclass(frozen=True, slots=True)
class VideoPreferences(BinaryStruct):
    """Language and the retained legacy field in the 2,924-byte layout.

    The public timezone_code name predates native qualification. In version
    0x39 this word stores alarm data, so PreferencesDocument suppresses its
    timezone interpretation while preserving the raw API and source bytes.
    """

    timezone_code: int = cf(PREFERENCES_ALARM_OFFSET, "i16")
    language_code: int = cf(2808, "u8")


@dataclass(frozen=True, slots=True)
class Video13Preferences(VideoPreferences):
    """Qualified 1.3 language word; inherited B22 remains an alarm observation."""

    language_code: int = cf(0xAF8, "u32")


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
    language_code: int = cf(0xAF8, "u32")


CLASSIC_ALTERNATE_AUDIO_OFFSET = 0xB85


@dataclass(frozen=True, slots=True)
class Classic201Preferences(ClassicPreferences):
    """Qualified Classic fields; city is read-only and Alternate Audio stays raw.

    Alternate Audio uses 0 for Off and 1 for On, not a stream or language ID.
    Unknown byte values remain unchanged unless explicitly replaced with 0/1.
    """

    alternate_audio: int = cf(CLASSIC_ALTERNATE_AUDIO_OFFSET, "u8")


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
    if profile in OTHER_FIRMWARE_PREFERENCES_DEFINITIONS:
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
    | FirmwareLanguagePreferences
    | Mini2Preferences
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
    # None means reset semantics are unqualified, not that resets cannot occur.
    reset_word_offset: int | None = 4

    def matches(self, source: bytes) -> bool:
        """Check retained file framing without asserting identity or editability."""
        return len(source) in self.sizes and (
            self.format_version is None
            or int.from_bytes(source[:4], "little") == self.format_version
        )


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


OTHER_FIRMWARE_PREFERENCES_DEFINITIONS = {
    PreferencesProfile.MINI_1_1_4_1: PreferencesDefinition(
        PreferencesLayout.FOURTH_GENERATION, (2876,), Mini1Preferences, 0x16
    ),
    PreferencesProfile.MINI_2_1_4_1: PreferencesDefinition(
        PreferencesLayout.FOURTH_GENERATION, (2876,), Mini2Preferences, 0x16
    ),
    PreferencesProfile.VIDEO_1_3: PreferencesDefinition(
        PreferencesLayout.VIDEO, (2924,), Video13Preferences, 0x39
    ),
    PreferencesProfile.NANO_1_1_3_1: PreferencesDefinition(
        PreferencesLayout.FIRMWARE, (2916,), FirmwareLanguagePreferences, 0x37
    ),
    PreferencesProfile.NANO_3_1_1_3: PreferencesDefinition(
        PreferencesLayout.FIRMWARE, (2952,), FirmwareLanguagePreferences, 0x3C
    ),
    PreferencesProfile.NANO_4_1_0_4: PreferencesDefinition(
        PreferencesLayout.FIRMWARE, (2960,), FirmwareLanguagePreferences, 0x3E
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
    firmware = OTHER_FIRMWARE_PREFERENCES_DEFINITIONS.get(profile)
    if firmware is not None:
        return firmware if size in firmware.sizes else None
    return next((item for item in PREFERENCES_DEFINITIONS if size in item.sizes), None)


def matches_preferences_profile(source: bytes, profile: PreferencesProfile) -> bool:
    """Recognize an exact firmware frame without granting interpretation authority.

    Generic size-only layouts are deliberately excluded. A match can withhold an
    unsafe legacy interpretation but cannot identify the connected iPod.
    """
    if type(profile) is not PreferencesProfile:
        return False
    definition = definition_for_size(len(source), profile)
    return (
        definition is not None
        and definition.format_version is not None
        and definition.matches(source)
    )
