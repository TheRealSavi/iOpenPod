"""Typed settings resolution across global, device, and default values."""

import logging
from collections.abc import Callable, Mapping
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
    deviceStateChanged = Signal()
    deviceSaveRequested = Signal(object)

    def __init__(
        self,
        global_store: SettingsStore,
        device_store: DeviceSettingsStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._global = global_store
        self._device = device_store
        self._observed: dict[str, Callable[[], object]] = {}
        self._device_writable = False
        self._device_busy = False
        self._pending_device: dict[str, object] | None = None
        self._device_message = ""
        self._managed_device = False

    def get(self, definition: SettingDefinition[SettingValue]) -> SettingValue:
        self._observed[definition.key] = lambda: self._resolve(definition)[0]
        value, _source = self._resolve(definition)
        return value

    def get_global(self, definition: SettingDefinition[SettingValue]) -> SettingValue:
        """Read the Host value even when the Active iPod overrides it."""
        value = self._global.get(definition.key, definition.default)
        return value if definition.validate(value) else definition.default

    def device_edit_value(
        self, definition: SettingDefinition[SettingValue]
    ) -> tuple[SettingValue, bool]:
        """Preview a pending edit without changing confirmed runtime settings."""
        values = self._pending_device
        value = (
            values.get(definition.key)
            if values is not None
            else self._device.get(definition.key, None)
        )
        if definition.device_overridable and definition.validate(value):
            return value, True
        return self.get_global(definition), False

    @property
    def device_connected(self) -> bool:
        return self._device.connected

    @property
    def device_writable(self) -> bool:
        return (
            self._device.connected and self._device_writable and not self._device_busy
        )

    @property
    def device_busy(self) -> bool:
        return self._device_busy

    @property
    def device_message(self) -> str:
        return self._device_message

    def set_device_available(self, available: bool) -> None:
        if self._device_writable != available:
            self._device_writable = available
            self.deviceStateChanged.emit()

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
        self._require_device_write(definition)
        self._require_valid(definition, value)
        self.get(definition)
        values = self._device.values
        values[definition.key] = value
        self._save_device(values)

    def reset_device(self, definition: SettingDefinition[SettingValue]) -> None:
        self._require_device_write(definition)
        self.get(definition)
        values = self._device.values
        values.pop(definition.key, None)
        self._save_device(values)

    def _require_device_write(
        self, definition: SettingDefinition[SettingValue]
    ) -> None:
        if not definition.device_overridable:
            raise ValueError(f"{definition.key!r} is not device-overridable")
        if not self.device_writable:
            raise RuntimeError("The Active iPod settings are not available for editing")

    def _save_device(self, values: dict[str, object]) -> None:
        self._device_message = ""
        if self._managed_device:
            self._pending_device = dict(values)
            self._device_busy = True
            self.deviceStateChanged.emit()
            self.deviceSaveRequested.emit(values)
        else:
            self.complete_device_save(values)

    def complete_device_save(
        self, values: Mapping[str, object] | None, message: str = ""
    ) -> None:
        before = {key: read() for key, read in self._observed.items()}
        if values is not None and self._device.device_id is not None:
            self._device.load(self._device.device_id, values)
        self._device_busy = False
        self._pending_device = None
        self._device_message = message
        self._emit_effective_changes(before)
        self.deviceStateChanged.emit()

    def load_device(
        self,
        device_id: str,
        values: Mapping[str, object],
        *,
        writable: bool = True,
        managed: bool = False,
        message: str = "",
    ) -> None:
        before = {key: read() for key, read in self._observed.items()}
        self._device.load(device_id, values)
        self._device_writable = writable
        self._managed_device = managed
        self._device_busy = False
        self._pending_device = None
        self._device_message = message
        self._emit_effective_changes(before)
        self.deviceLoaded.emit(device_id)
        self.deviceStateChanged.emit()

    def unload_device(self) -> None:
        if not self._device.connected:
            return
        before = {key: read() for key, read in self._observed.items()}
        self._device.unload()
        self._device_writable = False
        self._device_busy = False
        self._pending_device = None
        self._device_message = ""
        self._emit_effective_changes(before)
        self.deviceUnloaded.emit()
        self.deviceStateChanged.emit()

    def _emit_effective_changes(self, before: Mapping[str, object]) -> None:
        for key, old in before.items():
            value = self._observed[key]()
            if value != old:
                self.settingChanged.emit(key, value)

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
