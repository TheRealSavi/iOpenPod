"""Lossless typed contracts for firmware Preferences and binary iTunesPrefs."""

from iPodDB.preferences.codec import parse_preferences, write_preferences
from iPodDB.preferences.definitions import (
    CityPreferences,
    FourthGenerationPreferences,
    Nano3Preferences,
    PreferencesLayout,
    PreferencesProfile,
    PreferencesSettings,
    VideoPreferences,
    VolumeLimitPreferences,
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
    "parse_itunes_preferences",
    "parse_preferences",
    "write_itunes_preferences",
    "write_preferences",
]
