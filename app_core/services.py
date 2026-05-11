"""Typed service interfaces and immutable runtime snapshots."""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import Any, Protocol, TypeGuard, runtime_checkable

from infrastructure.settings_schema import AppSettings, DeviceSettingsState


@runtime_checkable
class DeviceInfoLike(Protocol):
    """Device identity fields used across UI-facing service boundaries."""

    model_family: str
    generation: str
    color: str


def is_device_info_like(value: object) -> TypeGuard[DeviceInfoLike]:
    """Return whether a value exposes the minimum device identity fields."""

    return all(
        hasattr(value, field_name)
        for field_name in ("model_family", "generation", "color")
    )


@dataclass(frozen=True)
class SettingsSnapshot:
    """Immutable copy of user-configurable runtime settings."""

    settings_dir: str
    transcode_cache_dir: str
    max_cache_size_gb: float
    log_dir: str
    backup_dir: str
    media_folder: str
    write_back_to_pc: bool
    compute_sound_check: bool
    rotate_tall_photos_for_device: bool
    fit_photo_thumbnails: bool
    rating_conflict_strategy: str
    ffmpeg_path: str
    fpcalc_path: str
    lossy_encoder: str
    lossy_quality: str
    bitrate_mode: str
    music_lossy_cbr_bitrate: int
    vbr_level: int
    spoken_lossy_cbr_bitrate: int
    aac_cutoff: int
    aac_tns: bool
    aac_pns: bool
    aac_ms_stereo: bool
    aac_intensity_stereo: bool
    fdk_afterburner: bool
    video_crf: int
    video_preset: str
    prefer_lossy: bool
    sync_workers: int
    device_write_workers: int
    normalize_sample_rate: bool
    mono_for_spoken: bool
    smart_quality_by_type: bool
    last_device_path: str
    show_art_in_tracklist: bool
    rounded_artwork: bool
    sharpen_artwork: bool
    track_list_columns_by_content: dict[str, dict[str, int]]
    theme: str
    high_contrast: str
    font_scale: str
    accent_color: str
    window_width: int
    window_height: int
    splitter_sizes: tuple
    scrobble_on_sync: bool
    listenbrainz_token: str
    listenbrainz_username: str
    backup_before_sync: bool
    max_backups: int

    @classmethod
    def from_settings(cls, settings: AppSettings) -> SettingsSnapshot:
        data = {}
        for field_info in fields(cls):
            value = getattr(settings, field_info.name)
            if field_info.name == "splitter_sizes":
                value = tuple(value)
            elif field_info.name == "track_list_columns_by_content":
                value = copy.deepcopy(value)
            data[field_info.name] = value
        return cls(**data)


@dataclass(frozen=True)
class DeviceIdentitySnapshot:
    """Immutable identity fields for the active device."""

    path: str
    mount_name: str
    ipod_name: str
    display_name: str
    model_number: str
    model_family: str
    generation: str
    capacity: str
    color: str
    serial: str
    firewire_guid: str

    @classmethod
    def from_device_info(
        cls,
        device_info: object | None,
    ) -> DeviceIdentitySnapshot | None:
        if device_info is None:
            return None
        return cls(
            path=str(getattr(device_info, "path", "") or ""),
            mount_name=str(getattr(device_info, "mount_name", "") or ""),
            ipod_name=str(getattr(device_info, "ipod_name", "") or ""),
            display_name=str(getattr(device_info, "display_name", "") or ""),
            model_number=str(getattr(device_info, "model_number", "") or ""),
            model_family=str(getattr(device_info, "model_family", "") or ""),
            generation=str(getattr(device_info, "generation", "") or ""),
            capacity=str(getattr(device_info, "capacity", "") or ""),
            color=str(getattr(device_info, "color", "") or ""),
            serial=str(getattr(device_info, "serial", "") or ""),
            firewire_guid=str(getattr(device_info, "firewire_guid", "") or ""),
        )


@dataclass(frozen=True)
class DeviceCapabilitySnapshot:
    """Immutable capability fields used by UI and sync orchestration."""

    checksum: int
    is_shuffle: bool
    shadow_db_version: int
    supports_compressed_db: bool
    supports_video: bool
    supports_podcast: bool
    supports_gapless: bool
    supports_artwork: bool
    supports_photo: bool
    supports_sparse_artwork: bool
    supports_alac: bool
    music_dirs: int
    uses_sqlite_db: bool
    db_version: int
    byte_order: str
    has_screen: bool
    max_video_width: int
    max_video_height: int
    max_video_fps: int
    max_video_bitrate: int
    h264_level: str

    @classmethod
    def from_device_info(
        cls,
        device_info: object | None,
    ) -> DeviceCapabilitySnapshot | None:
        if device_info is None:
            return None
        try:
            capabilities = getattr(device_info, "capabilities", None)
        except Exception:
            capabilities = None
        if capabilities is None:
            return None
        return cls(
            checksum=int(getattr(capabilities, "checksum", 99) or 99),
            is_shuffle=bool(getattr(capabilities, "is_shuffle", False)),
            shadow_db_version=int(
                getattr(capabilities, "shadow_db_version", 0) or 0
            ),
            supports_compressed_db=bool(
                getattr(capabilities, "supports_compressed_db", False)
            ),
            supports_video=bool(getattr(capabilities, "supports_video", False)),
            supports_podcast=bool(getattr(capabilities, "supports_podcast", True)),
            supports_gapless=bool(getattr(capabilities, "supports_gapless", False)),
            supports_artwork=bool(getattr(capabilities, "supports_artwork", True)),
            supports_photo=bool(getattr(capabilities, "supports_photo", False)),
            supports_sparse_artwork=bool(
                getattr(capabilities, "supports_sparse_artwork", False)
            ),
            supports_alac=bool(getattr(capabilities, "supports_alac", True)),
            music_dirs=int(getattr(capabilities, "music_dirs", 20) or 20),
            uses_sqlite_db=bool(getattr(capabilities, "uses_sqlite_db", False)),
            db_version=int(getattr(capabilities, "db_version", 0) or 0),
            byte_order=str(getattr(capabilities, "byte_order", "le") or "le"),
            has_screen=bool(getattr(capabilities, "has_screen", True)),
            max_video_width=int(
                getattr(capabilities, "max_video_width", 0) or 0
            ),
            max_video_height=int(
                getattr(capabilities, "max_video_height", 0) or 0
            ),
            max_video_fps=int(getattr(capabilities, "max_video_fps", 30) or 30),
            max_video_bitrate=int(
                getattr(capabilities, "max_video_bitrate", 0) or 0
            ),
            h264_level=str(getattr(capabilities, "h264_level", "3.0") or "3.0"),
        )


@dataclass(frozen=True)
class DeviceSession:
    """Current device session state exposed to the UI."""

    device_path: str | None
    itunesdb_path: str | None
    artworkdb_path: str | None
    artwork_folder_path: str | None
    device_settings_loading: bool
    discovered_ipod: DeviceInfoLike | None
    identity: DeviceIdentitySnapshot | None
    capabilities: DeviceCapabilitySnapshot | None

    @property
    def has_device(self) -> bool:
        return bool(self.device_path)


@dataclass(frozen=True)
class LibrarySnapshot:
    """Current iTunesDB cache state exposed to the UI."""

    ready: bool
    loading: bool
    device_path: str | None
    track_count: int
    album_count: int
    playlist_count: int
    has_pending_playlists: bool
    has_pending_track_edits: bool
    has_pending_photo_edits: bool


class SettingsService(Protocol):
    """Typed access to global and effective settings state."""

    def get_global_settings(self) -> AppSettings:
        ...

    def get_effective_settings(self) -> AppSettings:
        ...

    def save_global_settings(self, settings: AppSettings) -> SettingsSnapshot:
        ...

    def device_settings_key(
        self,
        ipod_root: str = "",
        device_info: object | None = None,
    ) -> str:
        ...

    def get_device_settings_for_edit(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        ...

    def save_device_settings(
        self,
        ipod_root: str,
        settings: AppSettings,
        use_global_settings: bool = False,
        device_key: str = "",
    ) -> None:
        ...

    def reset_device_settings_to_global(
        self,
        ipod_root: str,
        device_key: str = "",
        use_global_settings: bool = False,
    ) -> AppSettings:
        ...

    def get_global_snapshot(self) -> SettingsSnapshot:
        ...

    def get_effective_snapshot(self) -> SettingsSnapshot:
        ...

    def reload(self) -> SettingsSnapshot:
        ...


class DeviceManagerLike(Protocol):
    """Runtime device manager surface exposed across the app-core boundary."""

    device_changed: Any
    device_settings_loaded: Any
    device_settings_failed: Any
    cancellation_token: Any

    @property
    def device_path(self) -> str | None:
        ...

    @device_path.setter
    def device_path(self, path: str | None) -> None:
        ...

    @property
    def discovered_ipod(self) -> DeviceInfoLike | None:
        ...

    @discovered_ipod.setter
    def discovered_ipod(self, ipod: DeviceInfoLike | None) -> None:
        ...

    @property
    def device_settings_loading(self) -> bool:
        ...

    @property
    def itunesdb_path(self) -> str | None:
        ...

    @property
    def artworkdb_path(self) -> str | None:
        ...

    @property
    def artwork_folder_path(self) -> str | None:
        ...

    def is_valid_ipod_root(self, path: str) -> bool:
        ...

    def cancel_all_operations(self) -> None:
        ...


class LibraryCacheLike(Protocol):
    """Runtime library cache surface exposed across the app-core boundary."""

    data_ready: Any
    playlists_changed: Any
    photos_changed: Any
    tracks_changed: Any
    playlist_quick_sync: Any

    @property
    def device_path(self) -> str | None:
        ...

    def clear(self) -> None:
        ...

    def invalidate(self) -> None:
        ...

    def start_loading(self) -> None:
        ...

    def is_ready(self) -> bool:
        ...

    def is_loading(self) -> bool:
        ...

    def get_data(self) -> dict | None:
        ...

    def get_tracks(self) -> list:
        ...

    def get_albums(self) -> list:
        ...

    def get_album_index(self) -> dict:
        ...

    def get_album_only_index(self) -> dict:
        ...

    def get_artist_index(self) -> dict:
        ...

    def get_genre_index(self) -> dict:
        ...

    def get_photo_db(self) -> Any:
        ...

    def replace_photo_db(self, photodb: Any) -> None:
        ...

    def get_track_id_index(self) -> dict:
        ...

    def get_playlists(self) -> list:
        ...

    def save_user_playlist(self, playlist: dict) -> None:
        ...

    def remove_user_playlist(self, playlist_id: int) -> bool:
        ...

    def update_track_flags(
        self,
        tracks: list[dict],
        changes: dict[str, Any],
    ) -> None:
        ...

    def get_user_playlists(self) -> list[dict]:
        ...

    def get_track_edits(self) -> dict[int, dict[str, tuple]]:
        ...

    def get_photo_edits(self) -> Any:
        ...

    def pop_track_edits(self) -> dict[int, dict[str, tuple]]:
        ...

    def has_pending_track_edits(self) -> bool:
        ...

    def has_pending_playlists(self) -> bool:
        ...

    def has_pending_photo_edits(self) -> bool:
        ...

    def clear_pending_sync_state(self) -> None:
        ...

    def clear_pending_playlists(self) -> None:
        ...

    def commit_user_playlists(self) -> None:
        ...


class DeviceSessionService(Protocol):
    """Typed access to the active device session."""

    def current_session(self) -> DeviceSession:
        ...

    def manager(self) -> DeviceManagerLike:
        ...


class LibraryService(Protocol):
    """Typed access to cached iTunesDB/library state."""

    def current_snapshot(self) -> LibrarySnapshot:
        ...

    def cache(self) -> LibraryCacheLike:
        ...
