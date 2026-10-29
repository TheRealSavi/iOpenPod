"""Keep the Jellyfin access token in a native OS vault, separate from preferences."""

import json
from dataclasses import asdict
from typing import Protocol, cast

import keyring
from keyring.backends.chainer import ChainerBackend

from ._json import is_object, text
from .models import JellyfinAccount, JellyfinError

_VAULT_SERVICE = "iOpenPod 2 Jellyfin"
_VAULT_KEY = "account"
_NATIVE_MODULES = frozenset(
    {
        "keyring.backends.Windows",
        "keyring.backends.macOS",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
    }
)


class TokenStore(Protocol):
    def load(self) -> JellyfinAccount | None: ...
    def save(self, account: JellyfinAccount) -> None: ...
    def remove(self) -> None: ...


class _NativeVault(Protocol):
    """Keyring's documented API, including its dynamically wrapped setter."""

    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class SystemTokenStore:
    def _backend(self) -> _NativeVault:
        backend = keyring.get_keyring()
        candidates = (
            backend.backends if isinstance(backend, ChainerBackend) else [backend]
        )
        for candidate in candidates:
            if type(candidate).__module__ in _NATIVE_MODULES:
                return cast("_NativeVault", candidate)
        raise JellyfinError(
            "A native system credential store is unavailable. Unlock or enable your OS keyring and try again."
        )

    def load(self) -> JellyfinAccount | None:
        try:
            raw = self._backend().get_password(_VAULT_SERVICE, _VAULT_KEY)
            if raw is None:
                return None
            values: object = json.loads(raw)
            if not is_object(values) or set(values) != {
                "server_url",
                "server_id",
                "user_id",
                "username",
                "device_id",
                "token",
            }:
                raise ValueError
            return JellyfinAccount(
                server_url=text(values["server_url"]),
                server_id=text(values["server_id"]),
                user_id=text(values["user_id"]),
                username=text(values["username"]),
                device_id=text(values["device_id"]),
                token=text(values["token"]),
            )
        except JellyfinError:
            raise
        except Exception:
            raise JellyfinError(
                "Could not read the Jellyfin sign-in from your OS keyring. Reconnect Jellyfin."
            ) from None

    def save(self, account: JellyfinAccount) -> None:
        try:
            self._backend().set_password(
                _VAULT_SERVICE, _VAULT_KEY, json.dumps(asdict(account))
            )
        except JellyfinError:
            raise
        except Exception:
            raise JellyfinError(
                "Could not save the Jellyfin sign-in in your OS keyring. Jellyfin was not connected."
            ) from None

    def remove(self) -> None:
        try:
            backend = self._backend()
            if backend.get_password(_VAULT_SERVICE, _VAULT_KEY) is not None:
                backend.delete_password(_VAULT_SERVICE, _VAULT_KEY)
        except JellyfinError:
            raise
        except Exception:
            raise JellyfinError(
                "Could not remove the Jellyfin sign-in from your OS keyring."
            ) from None
