"""Immutable native Preferences plus an explicit, host-independent zone reading."""

from dataclasses import dataclass, field

from iPodDB.preferences.definitions import (
    CityPreferences,
    ClassicPreferences,
    ExtendedPreferencesSettings,
    FourthGenerationPreferences,
    Mini2Preferences,
    NamedPreferencesProfile,
    PreferenceKey,
    PreferencesLayout,
    PreferencesProfile,
    PreferencesSettings,
    VideoPreferences,
    definition_for_size,
    matches_preferences_profile,
)
from iPodDB.preferences.timezones import (
    CITY_TIMEZONE_NAMES,
    CLASSIC_UNRESOLVED_CITY_IDS,
    TIME_ZONE_ALIASES,
)


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
    detail: str = ""


type PreferencesTimezone = FixedOffsetTimezone | CityTimezone


def read_timezone(settings: PreferencesSettings | None) -> PreferencesTimezone | None:
    """Project legacy fields without source framing or Host-clock access.

    Use PreferencesDocument.timezone for format-aware interpretation: this
    helper alone cannot reject Video 1.3's disproven alarm-word inference.
    """

    if isinstance(settings, Mini2Preferences):
        if not 1 <= settings.timezone_selector <= 50:
            return None
        pair, dst = divmod(settings.timezone_selector - 1, 2)
        return FixedOffsetTimezone((pair - 12 + dst) * 3600)
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
    if isinstance(settings, (CityPreferences, ClassicPreferences)):
        name = CITY_TIMEZONE_NAMES.get(settings.city_id)
        detail = ""
        if (
            isinstance(settings, ClassicPreferences)
            and settings.city_id in CLASSIC_UNRESOLVED_CITY_IDS
        ):
            name = None
            detail = "Classic city 0x26 has no verified geographical timezone. Its firmware offset conflicts with the legacy London mapping; a database-header fallback cannot recover historical city rules."
        elif isinstance(settings, ClassicPreferences) and settings.city_id == 0:
            name = None
            detail = "Classic city 0 has no verified geographical timezone. Firmware clock synchronization can select this value when no city matches the live clock settings."
        return CityTimezone(
            settings.city_id,
            TIME_ZONE_ALIASES.get(name, name) if name is not None else None,
            detail,
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
    # Retain the source for compare-before-write and exact unknown-byte retention.
    preference_edits: tuple[tuple[PreferenceKey, int], ...] = ()

    @property
    def reset_requested(self) -> bool | None:
        """Observe the loader's reset word for an exact qualified current frame.

        Only profiles with an independently traced reset word interpret it.
        A nonzero word makes those loaders discard saved settings and use
        defaults. This observes retained bytes, not whether a running device
        has applied them or who requested a reset. Unqualified reset semantics,
        generic/opaque layouts and mismatched framing return None. No bytes are
        normalized; None must not be treated as a cleared reset request.
        See docs/research/preferences-classic-writes-2026-11-07.md and
        docs/research/preferences-mini-video-writes-2026-11-07.md.
        """
        if type(self.profile) is not PreferencesProfile:
            return None
        definition = definition_for_size(len(self.source_bytes), self.profile)
        if (
            definition is None
            or definition.format_version is None
            or definition.reset_word_offset is None
            or self.layout is not definition.layout
            or not definition.matches(self.source_bytes)
        ):
            return None
        offset = definition.reset_word_offset
        return int.from_bytes(self.source_bytes[offset : offset + 4], "little") != 0

    @property
    def has_video13_framing(self) -> bool:
        """Observe the saved format, without asserting the connected identity.

        Video 1.3 stores an alarm word at the legacy timezone-code offset.
        This exact extent/version must therefore suppress that interpretation
        even when updater-family or release evidence is unavailable. See
        docs/research/mini-video-datetime-support-audit-2026-11-06.md.
        """
        return self.layout is PreferencesLayout.VIDEO and matches_preferences_profile(
            self.source_bytes, PreferencesProfile.VIDEO_1_3
        )

    @property
    def timezone(self) -> PreferencesTimezone | None:
        if self.has_video13_framing:
            return None
        return read_timezone(self.settings)


@dataclass(frozen=True, slots=True)
class NamedPreferencesDocument:
    source_bytes: bytes = field(repr=False)
    profile: NamedPreferencesProfile
    issues: tuple[str, ...] = ()
    preference_edits: tuple[tuple[PreferenceKey, int], ...] = ()
