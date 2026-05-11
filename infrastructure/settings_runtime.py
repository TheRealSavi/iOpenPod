"""Active settings runtime state and on-device settings coordination."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from importlib import import_module

from .settings_persistence import load_app_settings, save_app_settings
from .settings_schema import (
    DEVICE_SECRET_KEYS,
    DEVICE_SETTING_KEYS,
    AppSettings,
    DeviceSettingsState,
)
from .settings_secrets import (
    decrypt_secret_for_device,
    encrypt_secret,
    normalized_device_identity_value,
    normalized_device_mount_key,
)

logger = logging.getLogger(__name__)

DEVICE_SETTINGS_RELATIVE = os.path.join("iPod_Control", "iOpenPod", "settings.json")


def _copy_settings(settings: AppSettings) -> AppSettings:
    """Return a detached copy of settings, including mutable fields."""

    return copy.deepcopy(settings)


def _copy_device_settings_state(state: DeviceSettingsState) -> DeviceSettingsState:
    """Return a detached copy of loaded device settings state."""

    return DeviceSettingsState(
        settings=_copy_settings(state.settings),
        use_global_settings=bool(state.use_global_settings),
        exists=bool(state.exists),
        path=state.path,
    )


def _coerce_setting_value(current_value, value):
    expected_type = type(current_value)
    if expected_type is bool:
        return value if isinstance(value, bool) else None
    if expected_type is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None
    if expected_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    if expected_type is dict:
        return value if isinstance(value, dict) else None
    if expected_type is list:
        return value if isinstance(value, list) else None
    return value if isinstance(value, expected_type) else None


def _apply_settings_values(settings: AppSettings, data: dict, allowed_keys) -> None:
    for key in allowed_keys:
        if key not in data or not hasattr(settings, key):
            continue
        coerced = _coerce_setting_value(getattr(settings, key), data[key])
        if coerced is not None:
            setattr(settings, key, coerced)


def _clear_transcoder_caches() -> None:
    try:
        import_module("SyncEngine.transcoder").clear_caches()
    except Exception:
        logger.debug("Failed to clear transcoder caches", exc_info=True)


def _same_root(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def device_settings_path(ipod_root: str) -> str:
    return os.path.join(ipod_root, DEVICE_SETTINGS_RELATIVE)


def has_device_settings(ipod_root: str) -> bool:
    return bool(ipod_root) and os.path.exists(device_settings_path(ipod_root))


def device_settings_key(ipod_root: str = "", device_info=None) -> str:
    """Build a stable-ish key for lightly obfuscating on-device secrets."""

    candidates = []
    if device_info is not None:
        for attr in ("firewire_guid", "serial", "serial_number", "model_number"):
            value = normalized_device_identity_value(getattr(device_info, attr, ""))
            if value:
                candidates.append(value)
    if candidates:
        return "|".join(candidates)

    mount_key = normalized_device_mount_key(ipod_root)
    if mount_key:
        return mount_key
    return "unknown-device"


def _serialized_device_settings(settings: AppSettings, device_key: str) -> dict:
    data = {}
    for key in DEVICE_SETTING_KEYS:
        value = getattr(settings, key)
        if key in DEVICE_SECRET_KEYS:
            value = encrypt_secret(value, device_key)
        data[key] = value
    return data


class SettingsRuntime:
    """Synchronized owner for mutable global/effective settings state."""

    def __init__(self) -> None:
        self._global_settings: AppSettings | None = None
        self._effective_settings: AppSettings | None = None
        self._active_device_state: DeviceSettingsState | None = None
        self._active_device_root = ""
        self._active_device_key = ""
        self._active_device_use_global = False
        self._lock = threading.RLock()

    def _get_global_settings_unlocked(self) -> AppSettings:
        if self._global_settings is None:
            self._global_settings = load_app_settings()
        if self._effective_settings is None:
            self._effective_settings = self._global_settings
        return self._global_settings

    def _load_device_settings_unlocked(
        self,
        ipod_root: str,
        device_key: str = "",
        base_settings: AppSettings | None = None,
    ) -> DeviceSettingsState:
        base = _copy_settings(base_settings or self._get_global_settings_unlocked())
        path = device_settings_path(ipod_root)
        if not ipod_root or not os.path.exists(path):
            return DeviceSettingsState(settings=base, exists=False, path=path)

        try:
            with open(path, encoding="utf-8") as file:
                raw = json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return DeviceSettingsState(settings=base, exists=True, path=path)

        if not isinstance(raw, dict):
            return DeviceSettingsState(settings=base, exists=True, path=path)

        use_global = bool(raw.get("use_global_settings", False))
        data = raw.get("settings", raw)
        if not isinstance(data, dict):
            data = {}
        stored_key_hint = str(raw.get("device_key_hint", "") or "")

        decoded = dict(data)
        for key in DEVICE_SECRET_KEYS:
            if key in decoded and isinstance(decoded[key], str):
                decoded[key] = decrypt_secret_for_device(
                    decoded[key],
                    device_key=device_key,
                    ipod_root=ipod_root,
                    stored_hint=stored_key_hint,
                )

        _apply_settings_values(base, decoded, DEVICE_SETTING_KEYS)
        return DeviceSettingsState(
            settings=base,
            use_global_settings=use_global,
            exists=True,
            path=path,
        )

    def _activate_device_settings_unlocked(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        global_settings = self._get_global_settings_unlocked()
        state = self._load_device_settings_unlocked(
            ipod_root,
            device_key,
            global_settings,
        )
        self._active_device_root = ipod_root or ""
        self._active_device_key = device_key or ""
        self._active_device_use_global = bool(state.use_global_settings)
        self._active_device_state = _copy_device_settings_state(state)
        self._effective_settings = (
            global_settings
            if (not state.exists or state.use_global_settings)
            else state.settings
        )
        return state

    def get_global_settings(self) -> AppSettings:
        """Get the PC/global settings instance."""

        with self._lock:
            return self._get_global_settings_unlocked()

    def get_settings(self) -> AppSettings:
        """Get settings currently effective for the selected device."""

        with self._lock:
            if self._effective_settings is None:
                self._effective_settings = self._get_global_settings_unlocked()
            return self._effective_settings

    def save_global_settings(self, settings: AppSettings) -> AppSettings:
        """Persist PC/global settings and refresh effective runtime state."""

        with self._lock:
            save_app_settings(settings)
            self._global_settings = settings
            _clear_transcoder_caches()
            return self.refresh_effective_settings()

    def reload_settings(self) -> AppSettings:
        """Force reload from disk, preserving the active device overlay."""

        with self._lock:
            self._global_settings = load_app_settings()
            if self._active_device_root:
                self._activate_device_settings_unlocked(
                    self._active_device_root,
                    self._active_device_key,
                )
                effective = self._effective_settings
            else:
                effective = self._global_settings
                self._effective_settings = effective
        assert effective is not None
        return effective

    def load_device_settings(
        self,
        ipod_root: str,
        device_key: str = "",
        base_settings: AppSettings | None = None,
    ) -> DeviceSettingsState:
        if base_settings is None:
            with self._lock:
                base_settings = _copy_settings(self._get_global_settings_unlocked())
        return self._load_device_settings_unlocked(
            ipod_root,
            device_key,
            base_settings,
        )

    def get_device_settings_for_edit(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        """Load device settings, or initialize an unsaved edit copy from globals."""

        active_state = self.get_active_device_settings_state(ipod_root, device_key)
        if active_state is not None:
            return active_state
        return self.load_device_settings(
            ipod_root,
            device_key,
            self.get_global_settings(),
        )

    def save_device_settings(
        self,
        ipod_root: str,
        settings: AppSettings,
        use_global_settings: bool = False,
        device_key: str = "",
    ) -> None:
        path = device_settings_path(ipod_root)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "use_global_settings": bool(use_global_settings),
            "settings": _serialized_device_settings(settings, device_key),
        }
        if device_key and device_key != "unknown-device":
            payload["device_key_hint"] = device_key
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

        _clear_transcoder_caches()
        with self._lock:
            if self._active_device_root and _same_root(
                self._active_device_root,
                ipod_root,
            ):
                state = DeviceSettingsState(
                    settings=_copy_settings(settings),
                    use_global_settings=bool(use_global_settings),
                    exists=True,
                    path=path,
                )
                global_settings = self._get_global_settings_unlocked()
                self._active_device_root = ipod_root or ""
                self._active_device_key = device_key or ""
                self._active_device_use_global = bool(use_global_settings)
                self._active_device_state = state
                self._effective_settings = (
                    global_settings if use_global_settings else state.settings
                )

    def reset_device_settings_to_global(
        self,
        ipod_root: str,
        device_key: str = "",
        use_global_settings: bool = False,
    ) -> AppSettings:
        """Replace the on-iPod settings file with current global device settings."""

        settings = _copy_settings(self.get_global_settings())
        self.save_device_settings(
            ipod_root,
            settings,
            use_global_settings=use_global_settings,
            device_key=device_key,
        )
        return settings

    def apply_loaded_device_settings(
        self,
        ipod_root: str,
        device_key: str,
        state: DeviceSettingsState,
    ) -> AppSettings:
        """Activate a device-settings state that was loaded off the UI thread."""

        with self._lock:
            global_settings = self._get_global_settings_unlocked()
            state_copy = _copy_device_settings_state(state)
            self._active_device_root = ipod_root or ""
            self._active_device_key = device_key or ""
            self._active_device_use_global = bool(state_copy.use_global_settings)
            self._active_device_state = state_copy
            self._effective_settings = (
                global_settings
                if (not state_copy.exists or state_copy.use_global_settings)
                else state_copy.settings
            )
            return self._effective_settings

    def activate_device_settings(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        """Activate on-device settings for the selected iPod, if present."""

        with self._lock:
            return self._activate_device_settings_unlocked(ipod_root, device_key)

    def clear_device_settings(self) -> AppSettings:
        """Return to the global settings profile."""

        with self._lock:
            self._active_device_root = ""
            self._active_device_key = ""
            self._active_device_use_global = False
            self._active_device_state = None
            self._effective_settings = self._get_global_settings_unlocked()
            return self._effective_settings

    def get_active_device_settings_state(
        self,
        ipod_root: str = "",
        device_key: str = "",
    ) -> DeviceSettingsState | None:
        """Return the active device settings state without reading the iPod."""

        with self._lock:
            if self._active_device_state is None or not self._active_device_root:
                return None
            if ipod_root and not _same_root(self._active_device_root, ipod_root):
                return None
            if device_key and device_key != self._active_device_key:
                return None
            return _copy_device_settings_state(self._active_device_state)

    def refresh_effective_settings(self) -> AppSettings:
        """Rebuild the effective settings after global settings were saved."""

        with self._lock:
            global_settings = self._get_global_settings_unlocked()
            if self._active_device_root:
                state = self._active_device_state
                if state is not None and state.exists and not state.use_global_settings:
                    refreshed = _copy_settings(global_settings)
                    for key in DEVICE_SETTING_KEYS:
                        if hasattr(refreshed, key) and hasattr(state.settings, key):
                            setattr(refreshed, key, getattr(state.settings, key))
                    self._active_device_state = DeviceSettingsState(
                        settings=refreshed,
                        use_global_settings=state.use_global_settings,
                        exists=state.exists,
                        path=state.path,
                    )
                    self._effective_settings = refreshed
                    effective = refreshed
                else:
                    self._effective_settings = global_settings
                    effective = global_settings
            else:
                self._effective_settings = global_settings
                effective = global_settings
            assert effective is not None
            return effective


_default_runtime = SettingsRuntime()


def get_default_runtime() -> SettingsRuntime:
    """Return the process-wide settings runtime used by app-core services."""

    return _default_runtime
