"""
Application settings with JSON persistence.

Settings are stored in the user's app data directory:
  Windows: %APPDATA%/iOpenPod/settings.json
  macOS:   ~/Library/Application Support/iOpenPod/settings.json
  Linux:   ~/.config/iOpenPod/settings.json

The default location always acts as a bootstrap: if it contains a
``settings_dir`` override, the real settings are loaded/saved from
that directory instead.  A small redirect file is kept at the default
location so the next launch can find the custom path.
"""

import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional


def _default_settings_dir() -> str:
    """Get the platform-appropriate *default* settings directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "iOpenPod")


def _get_settings_dir() -> str:
    """
    Resolve the active settings directory.

    Checks the default location for a ``settings_dir`` redirect.  If the
    redirect points to a valid directory, that directory is used.  Otherwise
    the default is used.
    """
    default_dir = _default_settings_dir()
    redirect_path = os.path.join(default_dir, "settings.json")

    if os.path.exists(redirect_path):
        try:
            with open(redirect_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            custom = data.get("settings_dir", "")
            if custom and os.path.isdir(custom) and custom != default_dir:
                # Verify the custom location actually has (or can have) a settings file
                return custom
        except (json.JSONDecodeError, OSError):
            pass

    return default_dir


def _get_settings_path() -> str:
    return os.path.join(_get_settings_dir(), "settings.json")


@dataclass
class AppSettings:
    """All user-configurable settings."""

    # ── Paths ───────────────────────────────────────────────────────────────
    # Custom settings directory (empty = platform default).
    # Changing this moves settings storage to the new location.
    settings_dir: str = ""

    # Custom transcode cache directory (empty = ~/.iopenpod/transcode_cache).
    transcode_cache_dir: str = ""

    # ── Sync ────────────────────────────────────────────────────────────────
    # Default PC music folder for sync (remembered between sessions)
    music_folder: str = ""

    # Write play counts and ratings back to PC source files after sync.
    # Off by default — users must opt in to having source files modified.
    write_back_to_pc: bool = False

    # ── Transcoding ─────────────────────────────────────────────────────────
    # AAC bitrate for lossy transcodes (OGG/Opus/WMA → AAC).
    # Common values: 128, 192, 256, 320. Higher = better quality, more space.
    aac_bitrate: int = 256

    # FFmpeg timeout in seconds per file.
    transcode_timeout: int = 300

    # Number of parallel transcode/copy workers.
    # 0 = auto (CPU count), 1 = sequential (legacy behaviour).
    sync_workers: int = 0

    # ── Library ─────────────────────────────────────────────────────────────
    # Last selected iPod device path (remembered between sessions)
    last_device_path: str = ""

    # ── Appearance ──────────────────────────────────────────────────────────
    # Show album art in the track list view
    show_art_in_tracklist: bool = True

    def save(self) -> None:
        """Write settings to the active settings directory.

        If ``settings_dir`` is set, settings are written there **and** a
        small redirect file is kept at the default location so the next
        launch can find the custom path.
        """
        active_dir = self.settings_dir or _default_settings_dir()
        os.makedirs(active_dir, exist_ok=True)

        path = os.path.join(active_dir, "settings.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

        # Keep a redirect at the default location when using a custom dir
        default_dir = _default_settings_dir()
        if self.settings_dir and self.settings_dir != default_dir:
            self._write_redirect(default_dir, self.settings_dir)
        elif not self.settings_dir:
            # Using the default — clean up any stale redirect
            self._clean_redirect(default_dir)

    @staticmethod
    def _write_redirect(default_dir: str, custom_dir: str) -> None:
        """Write a minimal redirect file at the default location."""
        os.makedirs(default_dir, exist_ok=True)
        redirect = os.path.join(default_dir, "settings.json")
        try:
            with open(redirect, "w", encoding="utf-8") as f:
                json.dump({"settings_dir": custom_dir}, f, indent=2)
        except OSError:
            pass

    @staticmethod
    def _clean_redirect(default_dir: str) -> None:
        """
        If the default settings.json is a redirect-only file (no other
        meaningful keys), it will be overwritten by the normal save above,
        so nothing extra to do here.
        """
        pass

    @classmethod
    def load(cls) -> "AppSettings":
        """Load settings from JSON, returning defaults for missing keys."""
        path = _get_settings_path()
        settings = cls()
        if not os.path.exists(path):
            return settings
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return settings
            # Only set known fields — silently ignore unknown keys
            for key, value in data.items():
                if hasattr(settings, key):
                    expected_type = type(getattr(settings, key))
                    if isinstance(value, expected_type):
                        setattr(settings, key, value)
        except (json.JSONDecodeError, OSError):
            pass
        return settings


# ── Singleton accessor ──────────────────────────────────────────────────────

_instance: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    """Get the global settings instance (loaded once on first access)."""
    global _instance
    if _instance is None:
        _instance = AppSettings.load()
    return _instance


def reload_settings() -> AppSettings:
    """Force reload from disk."""
    global _instance
    _instance = AppSettings.load()
    return _instance
