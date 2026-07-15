"""JSON persistence for global application settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .media_folders import media_folder_entries_to_settings
from .settings_paths import (
    default_settings_dir,
    get_settings_path,
)
from .settings_schema import (
    BACKUP_BEFORE_SYNC_ASK,
    BACKUP_BEFORE_SYNC_AUTO,
    AppSettings,
    apply_backup_before_sync_mode,
    normalize_backup_before_sync_mode,
    normalize_player_position,
    normalize_theme_preferences,
)


def save_app_settings(settings: AppSettings) -> None:
    """Write settings to the active settings directory."""

    apply_backup_before_sync_mode(settings)
    settings.player_position = normalize_player_position(settings.player_position)
    normalize_theme_preferences(settings)
    active_dir = settings.settings_dir or default_settings_dir()
    os.makedirs(active_dir, exist_ok=True)

    path = os.path.join(active_dir, "settings.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as file:
            json.dump(asdict(settings), file, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

    default_dir = default_settings_dir()
    if settings.settings_dir and settings.settings_dir != default_dir:
        write_settings_redirect(default_dir, settings.settings_dir)


def write_settings_redirect(default_dir: str, custom_dir: str) -> None:
    """Write a minimal redirect file at the default settings location."""

    os.makedirs(default_dir, exist_ok=True)
    redirect = os.path.join(default_dir, "settings.json")
    try:
        with open(redirect, "w", encoding="utf-8") as file:
            json.dump({"settings_dir": custom_dir}, file, indent=2)
    except OSError:
        pass


def load_app_settings() -> AppSettings:
    """Load settings from JSON, returning defaults for missing keys."""

    path = get_settings_path()
    settings = AppSettings()
    if not os.path.exists(path):
        return settings
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return settings

        for key, value in data.items():
            if hasattr(settings, key):
                expected_type = type(getattr(settings, key))
                if isinstance(value, int) and expected_type is float:
                    value = float(value)
                if key == "media_folders" and isinstance(value, list):
                    value = media_folder_entries_to_settings(value)
                if isinstance(value, expected_type):
                    setattr(settings, key, value)
        if "backup_before_sync_mode" in data:
            settings.backup_before_sync_mode = normalize_backup_before_sync_mode(
                data.get("backup_before_sync_mode"),
                legacy_backup_before_sync=settings.backup_before_sync,
            )
        else:
            settings.backup_before_sync_mode = (
                BACKUP_BEFORE_SYNC_AUTO
                if settings.backup_before_sync
                else BACKUP_BEFORE_SYNC_ASK
            )
        settings.backup_before_sync = (
            settings.backup_before_sync_mode == BACKUP_BEFORE_SYNC_AUTO
        )
        settings.player_position = normalize_player_position(settings.player_position)
        normalize_theme_preferences(
            settings,
            migrate_legacy_theme="theme_mode" not in data,
        )

    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        pass
    return settings
