"""Documented iTunesPrefs fields, independent of firmware Preferences."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType

from iPodDB.shared.chunk import BinaryStruct
from iPodDB.shared.chunk_field import chunk_field as cf


class PreferenceToggle(IntEnum):
    DISABLED = 0
    ENABLED = 1


class SyncMode(IntEnum):
    MANUAL = 0
    AUTOMATIC = 1


class SyncSelection(IntEnum):
    ALL = 1
    SELECTED = 2


class ITunesPreferencesProfile(StrEnum):
    STANDARD = "standard"
    SHUFFLE = "shuffle"


@dataclass(frozen=True, slots=True)
class ITunesPreferences(BinaryStruct):
    """Native values; unknown flag codes remain integers, never coerced to bool.

    Use PreferenceToggle, SyncMode and SyncSelection for edits. The two library
    identifiers are independent retained bytes; changing one does not change the
    other. Capacity fields have unknown units and are observation-only.
    """

    setup_completed: int = cf(8, "u8")
    open_itunes_on_attach: int = cf(9, "u8")
    music_sync_mode: int = cf(10, "u8")
    music_sync_selection: int = cf(11, "u8")
    library_link_id: bytes = cf(12, "raw", size=8)
    disk_use_enabled: int = cf(31, "u8")
    sync_checked_only: int = cf(34, "u8")
    show_artwork: int = cf(49, "u8")
    sync_photos: int = cf(52, "u8")
    include_original_photos: int = cf(55, "u8")
    transcode_to_128kbps_aac: int = cf(72, "u8")
    keep_in_source_list: int = cf(73, "u8")
    podcast_sync_selection: int = cf(89, "u8")
    podcast_sync_mode: int = cf(90, "u8")
    secondary_library_link_id: bytes = cf(96, "raw", size=8)
    shuffle_music_capacity_raw: int = cf(104, "u16")
    shuffle_file_capacity_raw: int = cf(106, "u16")
    sound_check_enabled: int = cf(124, "u8")


# Semantic validation uses names, while byte positions/types remain solely above.
ITUNES_FIELD_VALUES = MappingProxyType(
    {
        "setup_completed": PreferenceToggle,
        "open_itunes_on_attach": PreferenceToggle,
        "music_sync_mode": SyncMode,
        "music_sync_selection": SyncSelection,
        "disk_use_enabled": PreferenceToggle,
        "sync_checked_only": PreferenceToggle,
        "show_artwork": PreferenceToggle,
        "sync_photos": PreferenceToggle,
        "include_original_photos": PreferenceToggle,
        "transcode_to_128kbps_aac": PreferenceToggle,
        "keep_in_source_list": PreferenceToggle,
        "podcast_sync_selection": SyncSelection,
        "podcast_sync_mode": SyncMode,
        "sound_check_enabled": PreferenceToggle,
    }
)
ITUNES_OBSERVATION_FIELDS = frozenset(
    ("shuffle_music_capacity_raw", "shuffle_file_capacity_raw")
)
ITUNES_PREFS_MIN_SIZE = 236


@dataclass(frozen=True, slots=True)
class ShuffleVoiceOverPreferences(BinaryStruct):
    """Optional later Shuffle field; absence is distinct from disabled."""

    voice_over_enabled: int = cf(249, "u8")

    @property
    def enabled(self) -> bool:
        return self.voice_over_enabled != 0
