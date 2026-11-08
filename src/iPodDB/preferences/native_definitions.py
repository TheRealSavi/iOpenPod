"""Native Preferences authoring definitions, separate from edit execution.

Each profile's byte locations, masks, coupled encodings and offered domains are
qualified together. Shared addresses never imply another firmware's support.
Observation catalogs remain broader and cannot supply an authoring definition.
See the qualification sources documented in native.py.
"""

from dataclasses import dataclass

from iPodDB.preferences.definitions import (
    CLASSIC_ALTERNATE_AUDIO_OFFSET,
    CLASSIC_PREFERENCES_DEFINITIONS,
    PreferenceField,
    PreferenceKey,
    PreferencesProfile,
)


@dataclass(frozen=True, slots=True)
class PairChoice:
    value: int
    primary: int
    secondary: int


@dataclass(frozen=True, slots=True)
class PairEncoding:
    """One logical choice spans two bytes, without normalizing retained state.

    The first occurrence of a logical value is its canonical write encoding.
    Additional occurrences can describe known no-op aliases. Only explicitly
    proved primary modes may ignore their secondary byte when being read.
    """

    secondary_offset: int
    choices: tuple[PairChoice, ...]
    ignored_secondary_modes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PreferenceEncoding:
    field: PreferenceField
    offset: int
    width: int
    mask: int | None = None
    signed: bool = False
    pair: PairEncoding | None = None


_COMMON = (
    PreferenceEncoding(
        PreferenceField(PreferenceKey.SHUFFLE_MODE, (0, 1, 2)),
        0x18,
        1,
        pair=PairEncoding(
            0x8A,
            (
                PairChoice(0, 0, 0),
                PairChoice(1, 1, 0),
                PairChoice(2, 1, 1),
                PairChoice(0, 0, 1),
            ),
        ),
    ),
    PreferenceEncoding(PreferenceField(PreferenceKey.REPEAT_MODE, (0, 1, 2)), 0x14, 4),
    PreferenceEncoding(PreferenceField(PreferenceKey.SOUND_CHECK, (0, 1)), 0xB16, 1),
)
_EQ = PreferenceEncoding(
    PreferenceField(PreferenceKey.EQ_PRESET, (0, *range(100, 122))), 0xB60, 2
)
_BRIGHTNESS = PreferenceEncoding(
    PreferenceField(PreferenceKey.BRIGHTNESS, minimum=0, maximum=100), 0xB54, 1
)
_CLASSIC_CLICKER = PreferenceEncoding(
    PreferenceField(PreferenceKey.CLICKER, (0, 3)), 0xAFC, 4, mask=3
)
_LEGACY_CLICKER = PreferenceEncoding(
    PreferenceField(PreferenceKey.CLICKER, (0, 1, 2, 3)), 0xAFC, 4, mask=3
)
_ALTERNATE_AUDIO = PreferenceEncoding(
    PreferenceField(PreferenceKey.ALTERNATE_AUDIO, (0, 1)),
    CLASSIC_ALTERNATE_AUDIO_OFFSET,
    1,
)
_AUDIOBOOK_SPEED = PreferenceEncoding(
    PreferenceField(PreferenceKey.AUDIOBOOK_SPEED, (-1, 0, 1)), 0xB38, 1, signed=True
)
_CONTACT_SORT = PreferenceEncoding(
    PreferenceField(PreferenceKey.CONTACT_SORT, (0, 1)), 0xB0C, 2
)
_CONTACT_DISPLAY = PreferenceEncoding(
    PreferenceField(PreferenceKey.CONTACT_DISPLAY, (0, 1)), 0xB14, 2
)
_MINI_BACKLIGHT = PreferenceEncoding(
    PreferenceField(PreferenceKey.BACKLIGHT_TIMEOUT, (0, 2, 3, 4, 5, 6)), 0xAF0, 4
)
_LEGACY_COLOR_BACKLIGHT = PreferenceEncoding(
    PreferenceField(PreferenceKey.BACKLIGHT_TIMEOUT, (0, 2, 3, 4, 5, 6, 8)), 0xAF0, 4
)
_MODERN_BACKLIGHT = PreferenceEncoding(
    # Latent selector 8 displays 15 Seconds but is not an offered choice.
    PreferenceField(PreferenceKey.BACKLIGHT_TIMEOUT, (0, 1, 2, 3, 4, 5, 6)),
    0xAF0,
    4,
)
_PHOTO_TOGGLES = (
    PreferenceEncoding(PreferenceField(PreferenceKey.PHOTO_SHUFFLE, (0, 1)), 0xB3C, 1),
    PreferenceEncoding(PreferenceField(PreferenceKey.PHOTO_REPEAT, (0, 1)), 0xB3D, 1),
)
_PHOTO_SECONDS = PreferenceEncoding(
    PreferenceField(PreferenceKey.PHOTO_DURATION, (0, 2, 3, 5, 10, 20)),
    0xB3E,
    1,
    signed=True,
)
_CLASSIC_NANO3_TRANSITION = PreferenceEncoding(
    PreferenceField(PreferenceKey.PHOTO_TRANSITION, (0, -1, 14, 5, 24, 1, 3)),
    0xB3B,
    1,
    pair=PairEncoding(
        0xB49,
        (
            PairChoice(0, 0xFE, 0),
            PairChoice(-1, 0xFF, 25),
            *(PairChoice(value, 0xFE, value) for value in (14, 5, 24, 1, 3)),
        ),
        ignored_secondary_modes=(0xFF,),
    ),
)
_NANO4_TRANSITION = PreferenceEncoding(
    PreferenceField(PreferenceKey.PHOTO_TRANSITION, (25, -1, 26, 27, 6, 5, 21)),
    0xB3B,
    1,
    pair=PairEncoding(
        0xB49,
        (
            PairChoice(25, 0xFE, 25),
            PairChoice(-1, 0xFF, 28),
            *(PairChoice(value, 0xFE, value) for value in (26, 27, 6, 5, 21)),
        ),
        ignored_secondary_modes=(0xFF,),
    ),
)
_NANO_VIDEO = (
    PreferenceEncoding(PreferenceField(PreferenceKey.TV_OUT, (0, 1, 2)), 0xB39, 1),
    PreferenceEncoding(PreferenceField(PreferenceKey.TV_SIGNAL, (0, 1)), 0xB3A, 1),
    PreferenceEncoding(PreferenceField(PreferenceKey.TV_SCREEN, (0, 1)), 0xB84, 1),
    PreferenceEncoding(
        PreferenceField(PreferenceKey.FIT_TO_SCREEN_DISABLED, (0, 1)), 0xB4D, 1
    ),
    _ALTERNATE_AUDIO,
)
_VIDEO_WIDESCREEN = PreferenceEncoding(
    # Older Video's byte has different meaning/polarity from modern Fit to Screen.
    PreferenceField(PreferenceKey.WIDESCREEN, (0, 1)),
    0xB4D,
    1,
)
_VOICE_MEMO_QUALITY = PreferenceEncoding(
    # Video only: this address is numeric EQ on modern targets, a latch on Nano1.
    PreferenceField(PreferenceKey.VOICE_MEMO_QUALITY, (0, 1)),
    0xB60,
    1,
)
_NANO1_NIKE = (
    PreferenceEncoding(
        PreferenceField(PreferenceKey.NIKE_SPOKEN_FEEDBACK, (0, 1, 2)), 0xB56, 1
    ),
    PreferenceEncoding(
        PreferenceField(PreferenceKey.NIKE_REMOTE_COMMANDS_DISABLED, (0, 1)), 0xB57, 1
    ),
)


def preference_encodings(profile: PreferencesProfile) -> tuple[PreferenceEncoding, ...]:
    """Return only independently qualified authoring definitions for this profile."""
    if profile in CLASSIC_PREFERENCES_DEFINITIONS:
        return (
            *_COMMON,
            _EQ,
            _BRIGHTNESS,
            _CLASSIC_CLICKER,
            _ALTERNATE_AUDIO,
            _MODERN_BACKLIGHT,
            *_PHOTO_TOGGLES,
            _PHOTO_SECONDS,
            _CLASSIC_NANO3_TRANSITION,
        )
    if profile in (
        PreferencesProfile.NANO_3_1_1_3,
        PreferencesProfile.NANO_4_1_0_4,
    ):
        # Each Nano has its own native UI/commit proof, including masked Clicker.
        # Nano4's transition IDs and Random sentinel differ from Nano3/Classic.
        return (
            *_COMMON,
            _EQ,
            _BRIGHTNESS,
            _LEGACY_CLICKER,
            _MODERN_BACKLIGHT,
            _CONTACT_SORT,
            *_PHOTO_TOGGLES,
            _PHOTO_SECONDS,
            (
                _NANO4_TRANSITION
                if profile is PreferencesProfile.NANO_4_1_0_4
                else _CLASSIC_NANO3_TRANSITION
            ),
            *_NANO_VIDEO,
        )
    if profile in (
        PreferencesProfile.MINI_1_1_4_1,
        PreferencesProfile.MINI_2_1_4_1,
        PreferencesProfile.NANO_1_1_3_1,
        PreferencesProfile.VIDEO_1_3,
    ):
        legacy = (
            *_COMMON,
            _LEGACY_CLICKER,
            _AUDIOBOOK_SPEED,
            _CONTACT_SORT,
            _CONTACT_DISPLAY,
        )
        if profile is PreferencesProfile.VIDEO_1_3:
            return (
                *legacy,
                _LEGACY_COLOR_BACKLIGHT,
                *_PHOTO_TOGGLES,
                _VIDEO_WIDESCREEN,
                _VOICE_MEMO_QUALITY,
            )
        if profile is PreferencesProfile.NANO_1_1_3_1:
            # Photo UI mutation qualification is narrower than its read model.
            # Nike distance units also change live workout targets: excluded.
            return (*legacy, _LEGACY_COLOR_BACKLIGHT, *_NANO1_NIKE)
        return (*legacy, _MINI_BACKLIGHT)
    return ()
