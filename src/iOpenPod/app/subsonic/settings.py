"""Only non-secret Subsonic preferences belong in global settings."""

from __future__ import annotations

from typing import Any

from iOpenPod.app.core.settings.definitions import SettingDefinition

from .credentials import SystemSubsonicCredentialStore

_DEFAULT_VAULT = SystemSubsonicCredentialStore()

SUBSONIC_URL = SettingDefinition[str](
    key="subsonic/url",
    value_type=str,
    default="",
)

SUBSONIC_USERNAME = SettingDefinition[str](
    key="subsonic/username",
    value_type=str,
    default="",
)

# Tuple of Subsonic playlist IDs selected by the user to sync.
SUBSONIC_PLAYLIST_IDS = SettingDefinition[tuple[str, ...]](
    key="subsonic/playlist-ids",
    value_type=tuple,
    default=(),
)

# Mapping of subsonic_id -> target_ipod_id or mode
SUBSONIC_PLAYLIST_MAPPINGS = SettingDefinition[dict[str, Any]](
    key="subsonic/playlist-mappings",
    value_type=dict,
    default={},
)


def get_subsonic_password(username: str) -> str:
    """Retrieve the stored Subsonic password from the native OS vault."""
    return _DEFAULT_VAULT.load_password(username)


def set_subsonic_password(username: str, password: str) -> None:
    """Save the Subsonic password in the native OS vault."""
    _DEFAULT_VAULT.save_password(username, password)


def delete_subsonic_password(username: str) -> None:
    """Remove the Subsonic password from the native OS vault."""
    _DEFAULT_VAULT.remove_password(username)
