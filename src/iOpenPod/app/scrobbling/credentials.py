"""Keep service credentials in a native OS vault, separate from preferences."""

import json
from dataclasses import asdict
from typing import Protocol

from iOpenPod.app.core.credential_vault import CredentialVault, native_credential_vault

from ._json import is_object, text
from .models import Credentials, ScrobbleError, Service


class CredentialStore(Protocol):
    def load(self, service: Service) -> Credentials | None: ...
    def save(self, service: Service, credentials: Credentials) -> None: ...
    def remove(self, service: Service) -> None: ...


class SystemCredentialStore:
    def _backend(self) -> CredentialVault:
        try:
            return native_credential_vault()
        except RuntimeError:
            raise ScrobbleError(
                "A native system credential store is unavailable. Unlock or enable your OS keyring and try again."
            ) from None

    def load(self, service: Service) -> Credentials | None:
        try:
            raw = self._backend().get_password("iOpenPod 2 Scrobbling", service.value)
            if raw is None:
                return None
            values: object = json.loads(raw)
            if not is_object(values) or set(values) != {
                "username",
                "token",
                "api_key",
                "api_secret",
            }:
                raise ValueError
            return Credentials(
                username=text(values["username"]),
                token=text(values["token"]),
                api_key=text(values["api_key"]),
                api_secret=text(values["api_secret"]),
            )
        except ScrobbleError:
            raise
        except Exception:
            raise ScrobbleError(
                "Could not read the service credentials from your OS keyring. Reconnect the service."
            ) from None

    def save(self, service: Service, credentials: Credentials) -> None:
        try:
            self._backend().set_password(
                "iOpenPod 2 Scrobbling", service.value, json.dumps(asdict(credentials))
            )
        except ScrobbleError:
            raise
        except Exception:
            raise ScrobbleError(
                "Could not save credentials in your OS keyring. The account was not connected."
            ) from None

    def remove(self, service: Service) -> None:
        try:
            backend = self._backend()
            if backend.get_password("iOpenPod 2 Scrobbling", service.value) is not None:
                backend.delete_password("iOpenPod 2 Scrobbling", service.value)
        except ScrobbleError:
            raise
        except Exception:
            raise ScrobbleError(
                "Could not remove credentials from your OS keyring."
            ) from None
