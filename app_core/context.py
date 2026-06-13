"""Composition root for application runtime services."""

from __future__ import annotations

from dataclasses import dataclass, field

from infrastructure.settings_runtime import SettingsRuntime, get_default_runtime
from infrastructure.settings_schema import AppSettings, DeviceSettingsState

from .services import (
    DeviceCapabilitySnapshot,
    DeviceIdentitySnapshot,
    DeviceManagerLike,
    DeviceSession,
    DeviceSessionService,
    LibraryCacheLike,
    LibraryService,
    LibrarySnapshot,
    SettingsService,
    SettingsSnapshot,
)


@dataclass
class RuntimeSettingsService:
    """App-core service wrapper around persisted runtime settings."""

    runtime: SettingsRuntime = field(default_factory=get_default_runtime)

    def get_global_settings(self) -> AppSettings:
        return self.runtime.get_global_settings()

    def get_effective_settings(self) -> AppSettings:
        return self.runtime.get_settings()

    def save_global_settings(self, settings: AppSettings) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(
            self.runtime.save_global_settings(settings)
        )

    def device_settings_key(
        self,
        ipod_root: str = "",
        device_info: object | None = None,
    ) -> str:
        from infrastructure.settings_runtime import device_settings_key

        return device_settings_key(ipod_root, device_info)

    def get_device_settings_for_edit(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        return self.runtime.get_device_settings_for_edit(ipod_root, device_key)

    def save_device_settings(
        self,
        ipod_root: str,
        settings: AppSettings,
        use_global_settings: bool = False,
        device_key: str = "",
    ) -> None:
        self.runtime.save_device_settings(
            ipod_root,
            settings,
            use_global_settings=use_global_settings,
            device_key=device_key,
        )

    def reset_device_settings_to_global(
        self,
        ipod_root: str,
        device_key: str = "",
        use_global_settings: bool = False,
    ) -> AppSettings:
        return self.runtime.reset_device_settings_to_global(
            ipod_root,
            device_key,
            use_global_settings=use_global_settings,
        )

    def get_global_snapshot(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self.get_global_settings())

    def get_effective_snapshot(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self.get_effective_settings())

    def reload(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self.runtime.reload_settings())


class RuntimeDeviceSessionService:
    """Compatibility wrapper around the runtime device manager."""

    def manager(self) -> DeviceManagerLike:
        from app_core.runtime import DeviceManager

        return DeviceManager.get_instance()

    def current_session(self) -> DeviceSession:
        manager = self.manager()
        discovered_ipod = manager.discovered_ipod
        return DeviceSession(
            device_path=manager.device_path,
            itunesdb_path=manager.itunesdb_path,
            artworkdb_path=manager.artworkdb_path,
            artwork_folder_path=manager.artwork_folder_path,
            device_settings_loading=manager.device_settings_loading,
            discovered_ipod=discovered_ipod,
            identity=DeviceIdentitySnapshot.from_device_info(discovered_ipod),
            capabilities=DeviceCapabilitySnapshot.from_device_info(discovered_ipod),
        )


class RuntimeLibraryService:
    """Compatibility wrapper around the runtime iTunesDB cache."""

    def cache(self) -> LibraryCacheLike:
        from app_core.runtime import iTunesDBCache

        return iTunesDBCache.get_instance()

    def current_snapshot(self) -> LibrarySnapshot:
        cache = self.cache()
        data = cache.get_data() or {}
        if data:
            from app_core.runtime import display_playlists_from_rows

            playlists = display_playlists_from_rows(cache.get_playlists())
        else:
            playlists = []
        return LibrarySnapshot(
            ready=cache.is_ready(),
            loading=cache.is_loading(),
            device_path=cache.device_path,
            track_count=len(data.get("mhlt", [])),
            album_count=len(data.get("mhla", [])),
            playlist_count=len(playlists),
            has_pending_playlists=cache.has_pending_playlists(),
            has_pending_track_edits=cache.has_pending_track_edits(),
            has_pending_photo_edits=cache.has_pending_photo_edits(),
        )


@dataclass(frozen=True)
class AppContext:
    """Composition-root container for runtime services."""

    settings: SettingsService
    device_sessions: DeviceSessionService
    libraries: LibraryService


def create_app_context() -> AppContext:
    """Create the default runtime context for the desktop app."""

    return AppContext(
        settings=RuntimeSettingsService(),
        device_sessions=RuntimeDeviceSessionService(),
        libraries=RuntimeLibraryService(),
    )
