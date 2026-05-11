"""Settings data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    "backup_before_sync",
)
DEVICE_SECRET_KEYS = {"listenbrainz_token"}


@dataclass
class AppSettings:
    """All user-configurable settings."""

    settings_dir: str = ""
    transcode_cache_dir: str = ""
    max_cache_size_gb: float = 5.0
    log_dir: str = ""
    backup_dir: str = ""

    media_folder: str = ""
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
    sync_workers: int = 0
    device_write_workers: int = 0
    normalize_sample_rate: bool = False
    mono_for_spoken: bool = True
    smart_quality_by_type: bool = True

    last_device_path: str = ""

    show_art_in_tracklist: bool = True
    rounded_artwork: bool = False
    sharpen_artwork: bool = True
    track_list_columns_by_content: dict[str, dict[str, int]] = field(default_factory=dict)
    theme: str = "dark"
    high_contrast: str = "off"
    font_scale: str = "100%"
    accent_color: str = "blue"
    window_width: int = 1280
    window_height: int = 720
    splitter_sizes: list = field(default_factory=list)

    scrobble_on_sync: bool = True
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""

    backup_before_sync: bool = True
    max_backups: int = 10


@dataclass
class DeviceSettingsState:
    """Loaded on-iPod settings plus metadata for the Settings page."""

    settings: AppSettings
    use_global_settings: bool = True
    exists: bool = False
    path: str = ""
