"""Keep Subsonic credentials in a native OS vault, separate from preferences."""

from __future__ import annotations

import logging
from typing import Protocol, cast

import keyring
from keyring.backends.chainer import ChainerBackend

from .client import SubsonicConnectionError

logger = logging.getLogger(__name__)

_SERVICE_NAME = "iOpenPod 2 Subsonic"

_NATIVE_MODULES = frozenset(
    {
        "keyring.backends.Windows",
        "keyring.backends.macOS",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
    }
)


class SubsonicCredentialStore(Protocol):
    """Abstract credential store protocol for Subsonic authentication."""

    def load_password(self, username: str) -> str: ...
    def save_password(self, username: str, password: str) -> None: ...
    def remove_password(self, username: str) -> None: ...


class _NativeVault(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class SystemSubsonicCredentialStore:
    """Store Subsonic passwords securely in the native OS vault (Keychain, Credential Manager, SecretService)."""

    def __init__(self) -> None:
        self._memory_fallback: dict[str, str] = {}

    def _backend(self) -> _NativeVault:
        backend = keyring.get_keyring()
        candidates = (
            backend.backends if isinstance(backend, ChainerBackend) else [backend]
        )
        for candidate in candidates:
            if type(candidate).__module__ in _NATIVE_MODULES:
                return cast("_NativeVault", candidate)
        raise SubsonicConnectionError(
            "A native system credential store is unavailable. Unlock or enable your OS keyring and try again."
        )

    def load_password(self, username: str) -> str:
        if not username:
            return ""
        try:
            pw = self._backend().get_password(_SERVICE_NAME, username)
            if pw:
                return pw
        except Exception as exc:
            logger.debug("Could not read password from native OS vault: %s", exc)
        return self._memory_fallback.get(username, "")

    def save_password(self, username: str, password: str) -> None:
        if not username:
            return
        if password:
            self._memory_fallback[username] = password
        else:
            self._memory_fallback.pop(username, None)
        try:
            backend = self._backend()
            if password:
                backend.set_password(_SERVICE_NAME, username, password)
            elif backend.get_password(_SERVICE_NAME, username) is not None:
                backend.delete_password(_SERVICE_NAME, username)
        except Exception as exc:
            logger.warning("Could not persist password in native OS vault: %s", exc)

    def remove_password(self, username: str) -> None:
        if not username:
            return
        self._memory_fallback.pop(username, None)
        try:
            backend = self._backend()
            if backend.get_password(_SERVICE_NAME, username) is not None:
                backend.delete_password(_SERVICE_NAME, username)
        except Exception as exc:
            logger.debug("Could not remove password from native OS vault: %s", exc)
