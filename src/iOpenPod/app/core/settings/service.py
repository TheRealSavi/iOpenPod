"""Typed settings resolution across global, device, and default values."""

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from PySide6.QtCore import QObject, Signal

from .definitions import SettingDefinition
from .stores import DeviceSettingsStore, SettingsStore

logger = logging.getLogger(__name__)
SettingValue = TypeVar("SettingValue")


class SettingSource(StrEnum):
    DEFAULT = "default"
    GLOBAL = "global"
    DEVICE = "device"


class SettingsService(QObject):
    """Resolve validated settings without exposing persistence details."""

    settingChanged = Signal(str, object)
    deviceLoaded = Signal(str)
    deviceUnloaded = Signal()

    def __init__(
        self,
        global_store: SettingsStore,
        device_store: DeviceSettingsStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._global = global_store
        self._device = device_store

    def get(self, definition: SettingDefinition[SettingValue]) -> SettingValue:
        value, _source = self._resolve(definition)
        return value

    def source(
        self,
        definition: SettingDefinition[SettingValue],
    ) -> SettingSource:
        _value, source = self._resolve(definition)
        return source

    def set_global(
        self,
        definition: SettingDefinition[SettingValue],
        value: SettingValue,
    ) -> None:
        self._require_valid(definition, value)
        self._global.set(definition.key, value)
        self._global.sync()
        effective = self.get(definition)
        self.settingChanged.emit(definition.key, effective)

    def reset_global(self, definition: SettingDefinition[SettingValue]) -> None:
        self._global.remove(definition.key)
        self._global.sync()
        self.settingChanged.emit(definition.key, self.get(definition))

    def set_device(
        self,
        definition: SettingDefinition[SettingValue],
        value: SettingValue,
    ) -> None:
        if not definition.device_overridable:
            raise ValueError(f"{definition.key!r} is not device-overridable")
        if not self._device.connected:
            raise RuntimeError("No Active iPod is loaded")
        self._require_valid(definition, value)
        self._device.set(definition.key, value)
        self.settingChanged.emit(definition.key, self.get(definition))

    def reset_device(self, definition: SettingDefinition[SettingValue]) -> None:
        self._device.remove(definition.key)
        self.settingChanged.emit(definition.key, self.get(definition))

    def load_device(
        self,
        device_id: str,
        values: Mapping[str, object],
    ) -> None:
        self._device.load(device_id, values)
        self.deviceLoaded.emit(device_id)

    def unload_device(self) -> None:
        if not self._device.connected:
            return
        self._device.unload()
        self.deviceUnloaded.emit()

    def sync(self) -> None:
        self._global.sync()

    def _resolve(
        self,
        definition: SettingDefinition[SettingValue],
    ) -> tuple[SettingValue, SettingSource]:
        candidates: tuple[tuple[SettingsStore, SettingSource], ...] = (
            (self._device, SettingSource.DEVICE),
            (self._global, SettingSource.GLOBAL),
        )

        for store, source in candidates:
            if source is SettingSource.DEVICE and not definition.device_overridable:
                continue
            if not store.has(definition.key):
                continue
            value = store.get(definition.key)
            if definition.validate(value):
                return value, source
            logger.warning(
                "Ignoring invalid %s setting value for %s: %r",
                source,
                definition.key,
                value,
            )

        return definition.default, SettingSource.DEFAULT

    @staticmethod
    def _require_valid(
        definition: SettingDefinition[SettingValue],
        value: object,
    ) -> None:
        if not definition.validate(value):
            raise ValueError(f"Invalid value for {definition.key!r}: {value!r}")
