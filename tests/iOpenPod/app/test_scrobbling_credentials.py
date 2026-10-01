"""Only native vault backends may persist service secrets."""

import json
from dataclasses import asdict

import keyring
import pytest

from iOpenPod.app.scrobbling.credentials import SystemCredentialStore
from iOpenPod.app.scrobbling.models import Credentials, ScrobbleError, Service


class VaultStub:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[service, username] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.values[service, username]


def test_plaintext_or_unrecognized_backend_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = VaultStub()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    with pytest.raises(ScrobbleError, match="native system"):
        SystemCredentialStore().save(Service.LASTFM, Credentials("alice", "secret"))
    assert not backend.values


def test_native_vault_roundtrip_and_service_isolated_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = VaultStub()
    monkeypatch.setattr(VaultStub, "__module__", "keyring.backends.Windows")
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    store = SystemCredentialStore()
    first, second = (
        Credentials("alice", "lf-session", "key", "secret"),
        Credentials("bob", "lb-token"),
    )
    store.save(Service.LASTFM, first)
    store.save(Service.LISTENBRAINZ, second)
    assert store.load(Service.LASTFM) == first
    assert store.load(Service.LISTENBRAINZ) == second
    serialized = backend.values["iOpenPod 2 Scrobbling", "lastfm"]
    assert json.loads(serialized)["api_secret"] == "secret"
    store.remove(Service.LASTFM)
    assert store.load(Service.LASTFM) is None
    assert store.load(Service.LISTENBRAINZ) == second


def test_malformed_vault_entry_is_reported_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = VaultStub()
    backend.values["iOpenPod 2 Scrobbling", "lastfm"] = "broken-secret"
    monkeypatch.setattr(VaultStub, "__module__", "keyring.backends.Windows")
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    with pytest.raises(ScrobbleError) as caught:
        SystemCredentialStore().load(Service.LASTFM)
    assert "broken-secret" not in str(caught.value)


@pytest.mark.parametrize("token", [None, 123, False, [], {}])
def test_vault_rejects_non_string_credentials(
    monkeypatch: pytest.MonkeyPatch, token: object
) -> None:
    backend = VaultStub()
    values: dict[str, object] = asdict(Credentials("alice", "secret", "key", "secret"))
    values["token"] = token
    raw = json.dumps(values)
    backend.values["iOpenPod 2 Scrobbling", "lastfm"] = raw
    monkeypatch.setattr(VaultStub, "__module__", "keyring.backends.Windows")
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    with pytest.raises(ScrobbleError) as caught:
        SystemCredentialStore().load(Service.LASTFM)
    assert "secret" not in str(caught.value)
    assert backend.values["iOpenPod 2 Scrobbling", "lastfm"] == raw
