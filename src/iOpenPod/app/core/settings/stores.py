"""Storage adapters for application and device settings."""

import base64
import binascii
import json
import logging
import math
from collections.abc import Mapping
from typing import Protocol, cast

from PySide6.QtCore import QByteArray

from storage import AtomicHostFile, Storage

MISSING = object()
logger = logging.getLogger(__name__)
_APPLICATION_NAME = "iOpenPod"
_SETTINGS_FILENAME = "settings-v2.json"


class SettingsStore(Protocol):
    """Small persistence seam consumed by :class:`SettingsService`."""

    def has(self, key: str) -> bool: ...

    def get(self, key: str, default: object = MISSING) -> object: ...

    def set(self, key: str, value: object) -> None: ...

    def remove(self, key: str) -> None: ...

    def sync(self) -> None: ...


class GlobalSettingsStore:
    """In-memory global store for tests and non-persistent compositions."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def has(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str, default: object = MISSING) -> object:
        if self.has(key):
            return self._values[key]
        if default is not MISSING:
            return default
        raise KeyError(key)

    def set(self, key: str, value: object) -> None:
        self._values[key] = value

    def remove(self, key: str) -> None:
        self._values.pop(key, None)

    def replace(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)

    def clear(self) -> None:
        self._values.clear()

    def sync(self) -> None:
        """Match the persistent-store interface without performing I/O."""


class JsonSettingsStore:
    """Persist typed global settings in one atomic, human-readable JSON file."""

    def __init__(self, host_file: AtomicHostFile) -> None:
        self._host_file = host_file
        self._values = _read_json_settings(host_file)
        self._dirty = False
        # Recovery belongs to the device journal, never to Host preferences.
        # Remove legacy hints even when their values are malformed or stale.
        for key in ("sync/pending-recovery-journal", "sync/pending-cleanup-journal"):
            self.remove(key)

    def has(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str, default: object = MISSING) -> object:
        if self.has(key):
            return self._values[key]
        if default is not MISSING:
            return default
        raise KeyError(key)

    def set(self, key: str, value: object) -> None:
        _encode_setting(value)
        if self._values.get(key, MISSING) == value:
            return
        self._values[key] = value
        self._dirty = True

    def remove(self, key: str) -> None:
        if key not in self._values:
            return
        del self._values[key]
        self._dirty = True

    def clear(self) -> None:
        if not self._values:
            return
        self._values.clear()
        self._dirty = True

    def sync(self) -> None:
        if not self._dirty:
            return
        payload = {
            key: _encode_setting(value) for key, value in sorted(self._values.items())
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        self._host_file.replace_bytes(f"{serialized}\n".encode())
        self._dirty = False


class DeviceSettingsStore:
    """In-memory values scoped to the one Active iPod."""

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._values: dict[str, object] = {}

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def connected(self) -> bool:
        return self._device_id is not None

    @property
    def values(self) -> dict[str, object]:
        return dict(self._values)

    def has(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str, default: object = MISSING) -> object:
        if self.has(key):
            return self._values[key]
        if default is not MISSING:
            return default
        raise KeyError(key)

    def set(self, key: str, value: object) -> None:
        self._values[key] = value

    def remove(self, key: str) -> None:
        self._values.pop(key, None)

    def load(self, device_id: str, values: Mapping[str, object]) -> None:
        self._device_id = device_id
        self._values = dict(values)

    def unload(self) -> None:
        self._device_id = None
        self._values.clear()

    def sync(self) -> None:
        """DeviceController coordinates persistence outside the GUI thread."""


def create_global_settings_store(storage: Storage) -> JsonSettingsStore:
    """Compose the global store through Storage's native Host-file boundary."""

    return JsonSettingsStore(
        storage.host_config_file(_APPLICATION_NAME, _SETTINGS_FILENAME)
    )


def _read_json_settings(host_file: AtomicHostFile) -> dict[str, object]:
    raw = host_file.read_bytes()
    if raw is None:
        return {}
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning("Ignoring malformed settings file %s: %s", host_file.path, error)
        return {}
    if not isinstance(payload, dict):
        logger.warning("Ignoring non-object settings file %s", host_file.path)
        return {}

    encoded_payload = cast("dict[object, object]", payload)
    values: dict[str, object] = {}
    for key, encoded in encoded_payload.items():
        if not isinstance(key, str):
            continue
        try:
            values[key] = _decode_setting(encoded)
        except ValueError as error:
            logger.warning("Ignoring invalid setting %s: %s", key, error)
    return values


def _encode_setting(value: object) -> object:
    if isinstance(value, QByteArray):
        return {
            "encoding": "base64",
            "type": "QByteArray",
            "value": base64.b64encode(value.data()).decode("ascii"),
        }
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_encode_setting(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        encoded: dict[str, object] = {}
        for key, item in cast("dict[object, object]", value).items():
            if not isinstance(key, str):
                raise TypeError("Settings object keys must be strings")
            encoded[key] = _encode_setting(item)
        return encoded
    raise TypeError(f"Unsupported settings value type: {type(value).__name__}")


def _decode_setting(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_decode_setting(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        encoded = cast("dict[object, object]", value)
        if encoded.get("type") == "QByteArray":
            encoded_value = encoded.get("value")
            if encoded.get("encoding") != "base64" or not isinstance(
                encoded_value, str
            ):
                raise ValueError("invalid QByteArray encoding")
            try:
                decoded = base64.b64decode(encoded_value, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("invalid QByteArray data") from error
            return QByteArray(decoded)
        decoded_object: dict[str, object] = {}
        for key, item in encoded.items():
            if not isinstance(key, str):
                raise ValueError("settings object keys must be strings")
            decoded_object[key] = _decode_setting(item)
        return decoded_object
    raise ValueError("unsupported value encoding")
