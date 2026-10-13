"""Compose Host tool preferences without exposing settings to Storage workers."""

from PySide6.QtCore import QObject

from iOpenPod.app.core.settings.definitions import MEDIA_TOOL_PATHS
from iOpenPod.app.core.settings.service import SettingsService
from storage import HostPath
from storage.media_processing import find_media_tool


class ConfiguredMediaTools(QObject):
    """Publish immutable path choices; consumers resolve them on their next lookup."""

    def __init__(self, settings: SettingsService) -> None:
        super().__init__(settings)
        self._settings = settings
        self._paths = self._read_paths()
        settings.settingChanged.connect(self._setting_changed)

    def _read_paths(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (name, self._settings.get_global(definition))
            for name, definition in MEDIA_TOOL_PATHS
        )

    def _setting_changed(self, key: str, _value: object) -> None:
        if any(key == definition.key for _, definition in MEDIA_TOOL_PATHS):
            self._paths = self._read_paths()

    def find(self, name: str) -> HostPath | None:
        for tool, path in self._paths:
            if tool == name and path:
                # Keep an explicit choice even if it cannot run. The normal
                # bounded tool invocation reports the failure without fallback.
                return HostPath(path)
        return find_media_tool(name)
