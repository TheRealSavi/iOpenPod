"""Select only native OS secret stores; never fall back to plaintext storage."""

from typing import Protocol, cast

import keyring
from keyring.backends.chainer import ChainerBackend

_NATIVE_MODULES = frozenset(
    {
        "keyring.backends.Windows",
        "keyring.backends.macOS",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
    }
)


class CredentialVault(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


def native_credential_vault() -> CredentialVault:
    backend = keyring.get_keyring()
    candidates = backend.backends if isinstance(backend, ChainerBackend) else [backend]
    for candidate in candidates:
        if type(candidate).__module__ in _NATIVE_MODULES:
            return cast("CredentialVault", candidate)
    raise RuntimeError("A native system credential store is unavailable.")
