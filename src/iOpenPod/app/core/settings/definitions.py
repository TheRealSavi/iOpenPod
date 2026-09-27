"""Typed definitions for application settings."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import TypeGuard

from PySide6.QtCore import QByteArray

from .paths import default_backup_path, default_log_path

type Validator[Value] = Callable[[Value], bool]


class PlayerPosition(StrEnum):
    """Stable positions for the full-width Player in the application shell."""

    TOP = "top"
    BOTTOM = "bottom"


class AppearanceMode(StrEnum):
    """Choose which appearance family is active."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class TrackTitleBarStyle(StrEnum):
    """Stable appearance choices for the Track-list title bar."""

    FLAT = "flat"
    ROUND = "round"


class IPodLibraryViewMode(StrEnum):
    """Choose how iPod Album and collection browsers present their Tracks."""

    SPLIT_TABLE = "split-table"
    WHOLE_PAGE_TABLE = "whole-page-table"


class LibraryDoubleClickShortcut(StrEnum):
    """Stable actions for double-clicking a Library Track selection."""

    ADD_TO_QUEUE = "add-to-queue"
    PLAY_NEXT = "play-next"
    PLAY_NOW = "play-now"
    EDIT = "edit"


class LightTheme(StrEnum):
    """Stable Light-theme selections."""

    PORCELAIN = "porcelain"
    CATPPUCCIN_LATTE = "catppuccin-latte"
    DUNE_PLOVER = "dune-plover"
    SEA_GLASS = "sea-glass"


class DarkTheme(StrEnum):
    """Stable Dark-theme selections."""

    SLATE = "slate"
    ORIGINAL = "original"
    CATPPUCCIN_FRAPPE = "catppuccin-frappe"
    CATPPUCCIN_MACCHIATO = "catppuccin-macchiato"
    CATPPUCCIN_MOCHA = "catppuccin-mocha"
    GRAVITY = "gravity"
    NORTHERN_LIGHTS = "northern-lights"
    ORCHID = "orchid"


@dataclass(frozen=True, slots=True)
class SettingDefinition[Value]:
    """Describe one stable setting key and its validation contract."""

    key: str
    value_type: type[Value]
    default: Value
    device_overridable: bool = False
    validator: Validator[Value] | None = None

    def validate(self, value: object) -> TypeGuard[Value]:
        if not isinstance(value, self.value_type):
            return False
        if self.validator is not None:
            return self.validator(value)
        return True


def _one_of(*allowed: str) -> Validator[str]:
    return lambda value: value in allowed


def _language_tag(value: str) -> bool:
    return 0 < len(value) <= 32 and all(
        character.isalnum() or character in {"-", "_"} for character in value
    )


def _optional_storage_identity(value: str) -> bool:
    return not value or (bool(value.strip()) and len(value) <= 4096)


def _absolute_path(value: str) -> bool:
    return bool(value.strip()) and len(value) <= 4096 and Path(value).is_absolute()


LOGGING_PATH = SettingDefinition[str](
    key="logging/path",
    value_type=str,
    default=str(default_log_path()),
)

# Preserve the existing v2 key: its System/Light/Dark value is now named Mode in
# the GUI, while the exact Light and Dark themes have independent keys below.
APPEARANCE_MODE = SettingDefinition[str](
    key="appearance/theme",
    value_type=str,
    default=AppearanceMode.SYSTEM.value,
    validator=_one_of(*(mode.value for mode in AppearanceMode)),
)

APPEARANCE_LIGHT_THEME = SettingDefinition[str](
    key="appearance/light-theme",
    value_type=str,
    default=LightTheme.PORCELAIN.value,
    validator=_one_of(*(theme.value for theme in LightTheme)),
)

APPEARANCE_DARK_THEME = SettingDefinition[str](
    key="appearance/dark-theme",
    value_type=str,
    default=DarkTheme.SLATE.value,
    validator=_one_of(*(theme.value for theme in DarkTheme)),
)

COLORFUL_MODE = SettingDefinition[bool](
    key="appearance/colorful-mode",
    value_type=bool,
    default=False,
)

TRACK_TITLE_BAR_STYLE = SettingDefinition[str](
    key="appearance/track-title-bar-style",
    value_type=str,
    default=TrackTitleBarStyle.FLAT.value,
    validator=_one_of(*(style.value for style in TrackTitleBarStyle)),
)

PLAYER_POSITION = SettingDefinition[str](
    key="appearance/player-position",
    value_type=str,
    default=PlayerPosition.TOP.value,
    validator=_one_of(*(position.value for position in PlayerPosition)),
)

APPLICATION_LANGUAGE = SettingDefinition[str](
    key="appearance/language",
    value_type=str,
    default="system",
    validator=_language_tag,
)

WINDOW_GEOMETRY = SettingDefinition[QByteArray](
    key="window/main/geometry",
    value_type=QByteArray,
    default=QByteArray(),
)

LIBRARY_SPLITTER_STATE = SettingDefinition[QByteArray](
    key="window/library/splitter-state",
    value_type=QByteArray,
    default=QByteArray(),
)

PHOTOS_SPLITTER_STATE = SettingDefinition[QByteArray](
    key="window/photos/splitter-state",
    value_type=QByteArray,
    default=QByteArray(),
)

LAST_SELECTED_IPOD_VOLUME_ID = SettingDefinition[str](
    key="devices/last-selected-volume-id",
    value_type=str,
    default="",
    validator=_optional_storage_identity,
)

DRAFT_ALL_CHANGES = SettingDefinition[bool](
    key="library/draft-all-changes",
    value_type=bool,
    default=False,
)

MANAGE_VOLUME_PRESENTATION = SettingDefinition[bool](
    key="devices/manage-volume-presentation",
    value_type=bool,
    default=True,
)

IPOD_LIBRARY_VIEW_MODE = SettingDefinition[str](
    key="library/ipod-view-mode",
    value_type=str,
    default=IPodLibraryViewMode.SPLIT_TABLE.value,
    validator=_one_of(*(mode.value for mode in IPodLibraryViewMode)),
)

LIBRARY_DOUBLE_CLICK_SHORTCUT = SettingDefinition[str](
    key="library/double-click-shortcut",
    value_type=str,
    default=LibraryDoubleClickShortcut.ADD_TO_QUEUE.value,
    validator=_one_of(*(action.value for action in LibraryDoubleClickShortcut)),
)

BACKUP_LOCATION = SettingDefinition[str](
    key="backups/location",
    value_type=str,
    default=str(default_backup_path()),
    validator=_absolute_path,
)

MAX_BACKUPS = SettingDefinition[int](
    key="backups/max-per-device",
    value_type=int,
    default=0,
    validator=lambda value: not isinstance(value, bool) and 0 <= value <= 1_000,
)


LOSSY_ENCODER = SettingDefinition[str](
    key="transcoding/lossy-encoder",
    value_type=str,
    default="auto",
    validator=_one_of("auto", "aac_at", "libfdk_aac", "aac", "libmp3lame"),
)
LOSSY_QUALITY = SettingDefinition[str](
    key="transcoding/quality",
    value_type=str,
    default="balanced",
    validator=_one_of("compact", "balanced", "high"),
)
TRANSCODE_LOSSLESS_TO_LOSSY = SettingDefinition[bool](
    key="transcoding/lossless-to-lossy", value_type=bool, default=False
)
RETRANSCODE_LOSSY = SettingDefinition[bool](
    key="transcoding/retranscode-lossy", value_type=bool, default=False
)
TRANSCODE_PCM_TO_ALAC = SettingDefinition[bool](
    key="transcoding/wav-aiff-to-alac", value_type=bool, default=True
)
NORMALIZE_SAMPLE_RATE = SettingDefinition[bool](
    key="transcoding/normalize-44100", value_type=bool, default=False
)
SMART_QUALITY_BY_CONTENT_TYPE = SettingDefinition[bool](
    key="transcoding/smart-spoken-word", value_type=bool, default=True
)
SPOKEN_WORD_MONO = SettingDefinition[bool](
    key="transcoding/spoken-word-mono", value_type=bool, default=True
)
SPOKEN_WORD_BITRATE = SettingDefinition[int](
    key="transcoding/spoken-word-bitrate-kbps",
    value_type=int,
    default=64,
    validator=lambda value: type(value) is int and value in (32, 48, 64, 80, 96),
)
COMPUTE_SOUND_CHECK = SettingDefinition[bool](
    key="sync/compute-sound-check", value_type=bool, default=False
)
NORMALIZE_TAGS_AFTER_SYNC = SettingDefinition[bool](
    key="sync/normalize-tags-after-sync", value_type=bool, default=False
)
ROTATE_TALL_PHOTOS = SettingDefinition[bool](
    key="sync/rotate-tall-photos", value_type=bool, default=False
)
FIT_THUMBNAILS = SettingDefinition[bool](
    key="sync/fit-thumbnails", value_type=bool, default=False
)
ROCKBOX_METADATA_SUPPORT = SettingDefinition[bool](
    key="sync/rockbox-metadata-support", value_type=bool, default=False
)


@cache
def table_header_state(table_id: str) -> SettingDefinition[QByteArray]:
    """Return the stable persisted-header setting for one named table."""

    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", table_id):
        raise ValueError(f"Invalid table identifier: {table_id!r}")
    return SettingDefinition[QByteArray](
        key=f"tables/{table_id}/header-state",
        value_type=QByteArray,
        default=QByteArray(),
    )
