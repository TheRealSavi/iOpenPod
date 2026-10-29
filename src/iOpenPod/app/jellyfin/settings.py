"""Only non-secret Jellyfin preferences belong in global settings."""

from iOpenPod.app.core.settings.definitions import SettingDefinition

JELLYFIN_SERVER_URL = SettingDefinition("jellyfin/server-url", str, "")
JELLYFIN_USERNAME = SettingDefinition("jellyfin/username", str, "")
# Reused across sign-ins so Jellyfin lists iOpenPod as one device.
JELLYFIN_DEVICE_ID = SettingDefinition("jellyfin/device-id", str, "")
