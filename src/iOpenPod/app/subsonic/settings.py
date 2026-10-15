"""Settings and credential storage for Subsonic integration."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import keyring

from iOpenPod.app.core.settings.definitions import SettingDefinition

logger = logging.getLogger(__name__)

SUBSONIC_SERVICE_KEY = "iOpenPod:Subsonic"

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
    """Retrieve the stored Subsonic password from the OS keyring."""
    if not username:
        return ""
    try:
        pw = keyring.get_password(SUBSONIC_SERVICE_KEY, username)
        return pw or ""
    except Exception as exc:
        logger.debug("Failed to read Subsonic password from keyring: %s", exc)
        return ""


def set_subsonic_password(username: str, password: str) -> None:
    """Save the Subsonic password in the OS keyring."""
    if not username:
        return
    try:
        if password:
            keyring.set_password(SUBSONIC_SERVICE_KEY, username, password)
        else:
            with contextlib.suppress(Exception):
                keyring.delete_password(SUBSONIC_SERVICE_KEY, username)
    except Exception as exc:
        logger.warning("Failed to save Subsonic password to keyring: %s", exc)


def delete_subsonic_password(username: str) -> None:
    """Remove the Subsonic password from the OS keyring."""
    if not username:
        return
    try:
        keyring.delete_password(SUBSONIC_SERVICE_KEY, username)
    except Exception as exc:
        logger.debug("Failed to delete Subsonic password from keyring: %s", exc)
