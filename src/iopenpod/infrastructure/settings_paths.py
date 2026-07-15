"""Platform-specific settings, data, and cache path resolution."""

from __future__ import annotations

import json
import os
import sys


def default_data_dir() -> str:
    """Base directory for iOpenPod user data such as logs and backups."""

    home = os.path.expanduser("~")
    legacy = os.path.join(home, "iOpenPod")

    if sys.platform == "win32":
        return legacy
    if sys.platform == "darwin":
        xdg = os.path.join(home, "Library", "Application Support", "iOpenPod")
        return legacy if os.path.isdir(legacy) else xdg

    if os.path.isdir(legacy):
        return legacy
    base = os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
    return os.path.join(base, "iOpenPod")


def default_cache_dir() -> str:
    """Base directory for iOpenPod cache data."""

    home = os.path.expanduser("~")
    legacy = os.path.join(home, "iOpenPod", "cache")

    if sys.platform == "win32":
        return legacy
    if sys.platform == "darwin":
        xdg = os.path.join(home, "Library", "Caches", "iOpenPod")
        return legacy if os.path.isdir(legacy) else xdg

    if os.path.isdir(legacy):
        return legacy
    base = os.environ.get("XDG_CACHE_HOME", os.path.join(home, ".cache"))
    return os.path.join(base, "iOpenPod")


def default_settings_dir() -> str:
    """Get the platform-appropriate default settings directory."""

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME",
            os.path.join(os.path.expanduser("~"), ".config"),
        )
    return os.path.join(base, "iOpenPod")


def get_settings_dir() -> str:
    """Resolve the active settings directory, following any redirect file."""

    default_dir = default_settings_dir()
    redirect_path = os.path.join(default_dir, "settings.json")

    if os.path.exists(redirect_path):
        try:
            with open(redirect_path, encoding="utf-8") as file:
                data = json.load(file)
            custom = data.get("settings_dir", "")
            if custom and os.path.isdir(custom) and custom != default_dir:
                return custom
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass

    return default_dir


def get_settings_path() -> str:
    """Return the active settings JSON path."""

    return os.path.join(get_settings_dir(), "settings.json")
