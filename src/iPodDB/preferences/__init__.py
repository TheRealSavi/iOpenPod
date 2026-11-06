"""Lossless typed contracts for firmware Preferences and binary iTunesPrefs."""

from iPodDB.preferences.codec import parse_preferences, write_preferences
from iPodDB.preferences.definitions import (
    CityPreferences,
    Classic201Preferences,
    ClassicClockPreferences,
    ClassicPreferences,
    FourthGenerationPreferences,
    Nano3Preferences,
    PreferencesLayout,
    PreferencesProfile,
    PreferencesSettings,
    VideoPreferences,
    VolumeLimitPreferences,
)
from iPodDB.preferences.dst import (
    DSTRule,
    DSTTableDocument,
    DSTTableIssue,
    DSTTableIssueCode,
    DSTTableProfile,
    DSTTransition,
    DSTWeek,
    parse_dst_table,
)
from iPodDB.preferences.itunes import (
    ITunesPreferencesDocument,
    parse_itunes_preferences,
    write_itunes_preferences,
)
from iPodDB.preferences.itunes_definitions import (
    ITunesPreferences,
    ITunesPreferencesProfile,
    PreferenceToggle,
    ShuffleVoiceOverPreferences,
    SyncMode,
    SyncSelection,
)
from iPodDB.preferences.models import (
    CityTimezone,
    FixedOffsetTimezone,
    PreferencesDocument,
    PreferencesTimezone,
)

__all__ = [
    "CityPreferences",
    "CityTimezone",
    "Classic201Preferences",
    "ClassicClockPreferences",
    "ClassicPreferences",
    "DSTRule",
    "DSTTableDocument",
    "DSTTableIssue",
    "DSTTableIssueCode",
    "DSTTableProfile",
    "DSTTransition",
    "DSTWeek",
    "FixedOffsetTimezone",
    "FourthGenerationPreferences",
    "ITunesPreferences",
    "ITunesPreferencesDocument",
    "ITunesPreferencesProfile",
    "Nano3Preferences",
    "PreferenceToggle",
    "PreferencesDocument",
    "PreferencesLayout",
    "PreferencesProfile",
    "PreferencesSettings",
    "PreferencesTimezone",
    "ShuffleVoiceOverPreferences",
    "SyncMode",
    "SyncSelection",
    "VideoPreferences",
    "VolumeLimitPreferences",
    "parse_dst_table",
    "parse_itunes_preferences",
    "parse_preferences",
    "write_itunes_preferences",
    "write_preferences",
]
