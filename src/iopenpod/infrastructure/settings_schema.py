"""Settings data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BACKUP_BEFORE_SYNC_AUTO = "auto"
BACKUP_BEFORE_SYNC_ASK = "ask"
BACKUP_BEFORE_SYNC_OFF = "off"
BACKUP_BEFORE_SYNC_MODES = frozenset({
    BACKUP_BEFORE_SYNC_AUTO,
    BACKUP_BEFORE_SYNC_ASK,
    BACKUP_BEFORE_SYNC_OFF,
})
PLAYER_POSITION_BOTTOM = "bottom"
PLAYER_POSITION_TOP = "top"
PLAYER_POSITIONS = frozenset({
    PLAYER_POSITION_BOTTOM,
    PLAYER_POSITION_TOP,
})
GRID_ITEM_SIZE_LARGE = "large"
GRID_ITEM_SIZE_SMALL = "small"
GRID_ITEM_SIZES = frozenset({
    GRID_ITEM_SIZE_LARGE,
    GRID_ITEM_SIZE_SMALL,
})
THEME_MODE_LIGHT = "light"
THEME_MODE_DARK = "dark"
THEME_MODE_AUTO = "auto"
THEME_MODES = frozenset({
    THEME_MODE_LIGHT,
    THEME_MODE_DARK,
    THEME_MODE_AUTO,
})
LIGHT_THEME_IDS = frozenset({"light", "catppuccin-latte"})
DARK_THEME_IDS = frozenset({
    "dark",
    "catppuccin-mocha",
    "catppuccin-macchiato",
    "catppuccin-frappe",
})

DEVICE_SETTING_KEYS = (
    "write_back_to_pc",
    "compute_sound_check",
    "rotate_tall_photos_for_device",
    "fit_photo_thumbnails",
    "rating_conflict_strategy",
    "lossy_encoder",
    "lossy_quality",
    "bitrate_mode",
    "music_lossy_cbr_bitrate",
    "vbr_level",
    "spoken_lossy_cbr_bitrate",
    "aac_cutoff",
    "aac_tns",
    "aac_pns",
    "aac_ms_stereo",
    "aac_intensity_stereo",
    "fdk_afterburner",
    "video_crf",
    "video_preset",
    "prefer_lossy",
    "always_encode_lossy",
    "convert_wav_to_alac",
    "sync_workers",
    "device_write_workers",
    "normalize_sample_rate",
    "mono_for_spoken",
    "smart_quality_by_type",
    "show_art_in_tracklist",
    "accent_color",
    "scrobble_on_sync",
    "listenbrainz_token",
    "listenbrainz_username",
    "lastfm_api_key",
    "lastfm_api_secret",
    "lastfm_session_key",
    "lastfm_username",
    "backup_before_sync",
    "backup_before_sync_mode",
    "normalize_tags_after_sync",
)
DEVICE_SECRET_KEYS = {"listenbrainz_token", "lastfm_api_key", "lastfm_api_secret", "lastfm_session_key"}


def normalize_backup_before_sync_mode(
    value: Any,
    *,
    legacy_backup_before_sync: bool = True,
) -> str:
    """Return canonical pre-sync backup mode."""

    if isinstance(value, bool):
        return BACKUP_BEFORE_SYNC_AUTO if value else BACKUP_BEFORE_SYNC_ASK
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "on": BACKUP_BEFORE_SYNC_AUTO,
            "always": BACKUP_BEFORE_SYNC_AUTO,
            "automatic": BACKUP_BEFORE_SYNC_AUTO,
            "enabled": BACKUP_BEFORE_SYNC_AUTO,
            "ask_each_time": BACKUP_BEFORE_SYNC_ASK,
            "ask_every_time": BACKUP_BEFORE_SYNC_ASK,
            "prompt": BACKUP_BEFORE_SYNC_ASK,
            "prompt_each_time": BACKUP_BEFORE_SYNC_ASK,
            "disabled": BACKUP_BEFORE_SYNC_OFF,
            "never": BACKUP_BEFORE_SYNC_OFF,
        }
        if normalized in BACKUP_BEFORE_SYNC_MODES:
            return normalized
        if normalized in aliases:
            return aliases[normalized]
    return (
        BACKUP_BEFORE_SYNC_AUTO
        if legacy_backup_before_sync
        else BACKUP_BEFORE_SYNC_ASK
    )


def apply_backup_before_sync_mode(settings: AppSettings) -> None:
    """Keep legacy bool in sync with canonical pre-sync backup mode."""

    if (
        settings.backup_before_sync_mode == BACKUP_BEFORE_SYNC_AUTO
        and not settings.backup_before_sync
    ):
        settings.backup_before_sync_mode = BACKUP_BEFORE_SYNC_ASK
        return
    settings.backup_before_sync_mode = normalize_backup_before_sync_mode(
        settings.backup_before_sync_mode,
        legacy_backup_before_sync=settings.backup_before_sync,
    )
    settings.backup_before_sync = (
        settings.backup_before_sync_mode == BACKUP_BEFORE_SYNC_AUTO
    )


def normalize_player_position(value: Any) -> str:
    """Return the canonical player dock position."""

    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "above": PLAYER_POSITION_TOP,
            "upper": PLAYER_POSITION_TOP,
            "below": PLAYER_POSITION_BOTTOM,
            "lower": PLAYER_POSITION_BOTTOM,
        }
        if normalized in PLAYER_POSITIONS:
            return normalized
        if normalized in aliases:
            return aliases[normalized]
    return PLAYER_POSITION_TOP


def normalize_grid_item_size(value: Any) -> str:
    """Return the canonical grid item size preset."""

    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "big": GRID_ITEM_SIZE_LARGE,
            "default": GRID_ITEM_SIZE_LARGE,
            "compact": GRID_ITEM_SIZE_SMALL,
        }
        if normalized in GRID_ITEM_SIZES:
            return normalized
        if normalized in aliases:
            return aliases[normalized]
    return GRID_ITEM_SIZE_LARGE


def normalize_theme_mode(value: Any) -> str:
    """Return the canonical appearance mode."""

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "system":
            return THEME_MODE_AUTO
        if normalized in THEME_MODES:
            return normalized
    return THEME_MODE_DARK


def normalize_light_theme(value: Any) -> str:
    """Return a valid light palette identifier."""

    if isinstance(value, str) and value in LIGHT_THEME_IDS:
        return value
    return "light"


def normalize_dark_theme(value: Any) -> str:
    """Return a valid dark palette identifier."""

    if isinstance(value, str) and value in DARK_THEME_IDS:
        return value
    return "dark"


@dataclass
class AppSettings:
    """All user-configurable settings."""

    settings_dir: str = ""
    transcode_cache_dir: str = ""
    max_cache_size_gb: float = 5.0
    log_dir: str = ""
    backup_dir: str = ""

    media_folder: str = ""
    media_folders: list[dict[str, object]] = field(default_factory=list)
    write_back_to_pc: bool = False
    compute_sound_check: bool = False
    rotate_tall_photos_for_device: bool = False
    fit_photo_thumbnails: bool = False
    rating_conflict_strategy: str = "ipod_wins"

    ffmpeg_path: str = ""
    fpcalc_path: str = ""

    lossy_encoder: str = "auto"
    lossy_quality: str = "balanced"
    bitrate_mode: str = "cbr"
    music_lossy_cbr_bitrate: int = 192
    vbr_level: int = 4
    spoken_lossy_cbr_bitrate: int = 64
    aac_cutoff: int = 0
    aac_tns: bool = True
    aac_pns: bool = False
    aac_ms_stereo: bool = True
    aac_intensity_stereo: bool = True
    fdk_afterburner: bool = True
    video_crf: int = 23
    video_preset: str = "fast"
    prefer_lossy: bool = False
    always_encode_lossy: bool = False
    convert_wav_to_alac: bool = True
    sync_workers: int = 0
    device_write_workers: int = 0
    normalize_sample_rate: bool = False
    mono_for_spoken: bool = True
    smart_quality_by_type: bool = True

    last_device_path: str = ""

    show_art_in_tracklist: bool = True
    rounded_artwork: bool = False
    sharpen_artwork: bool = True
    grid_item_size: str = GRID_ITEM_SIZE_LARGE
    track_list_columns_by_content: dict[str, dict[str, int]] = field(default_factory=dict)
    # ``theme`` is retained as a compatibility value for existing settings files
    # and third-party callers. New UI state lives in the three fields below.
    theme: str = "system"
    theme_mode: str = THEME_MODE_AUTO
    light_theme: str = "light"
    dark_theme: str = "dark"
    high_contrast: str = "off"
    font_scale: str = "100%"
    accent_color: str = "blue"
    player_position: str = PLAYER_POSITION_TOP
    window_width: int = 1280
    window_height: int = 720
    splitter_sizes: list = field(default_factory=list)

    scrobble_on_sync: bool = True
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""

    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_session_key: str = ""
    lastfm_username: str = ""

    backup_before_sync: bool = True
    backup_before_sync_mode: str = ""
    normalize_tags_after_sync: bool = False
    max_backups: int = 10

    def __post_init__(self) -> None:
        apply_backup_before_sync_mode(self)
        self.player_position = normalize_player_position(self.player_position)
        self.grid_item_size = normalize_grid_item_size(self.grid_item_size)


@dataclass
class DeviceSettingsState:
    """Loaded on-iPod settings plus metadata for the Settings page."""

    settings: AppSettings
    use_global_settings: bool = True
    exists: bool = False
    path: str = ""
    load_error: str = ""


def normalize_theme_preferences(
    settings: AppSettings,
    *,
    migrate_legacy_theme: bool = False,
) -> None:
    """Normalize split theme preferences and migrate the former single setting.

    Older settings files stored the selected palette (or ``"system"``) in
    ``theme``. The split preferences preserve that choice in the appropriate
    light or dark selector and choose the matching appearance mode.
    """

    if migrate_legacy_theme:
        legacy_theme = settings.theme
        if legacy_theme == "system":
            settings.theme_mode = THEME_MODE_AUTO
        elif legacy_theme in LIGHT_THEME_IDS:
            settings.theme_mode = THEME_MODE_LIGHT
            settings.light_theme = legacy_theme
        elif legacy_theme in DARK_THEME_IDS:
            settings.theme_mode = THEME_MODE_DARK
            settings.dark_theme = legacy_theme

    settings.theme_mode = normalize_theme_mode(settings.theme_mode)
    settings.light_theme = normalize_light_theme(settings.light_theme)
    settings.dark_theme = normalize_dark_theme(settings.dark_theme)

    # Keep the old field useful for integrations that have not moved to the
    # split preferences yet. It cannot represent Auto's two independent picks,
    # so Auto retains the historical "system" value.
    if settings.theme_mode == THEME_MODE_AUTO:
        settings.theme = "system"
    elif settings.theme_mode == THEME_MODE_LIGHT:
        settings.theme = settings.light_theme
    else:
        settings.theme = settings.dark_theme
