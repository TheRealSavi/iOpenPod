"""Credential input and Host persistence never become portable catalog data."""

import json

import pytest

from iOpenPod.app.podcasts import credentials as module
from iOpenPod.app.podcasts.credentials import (
    PodcastAccess,
    PodcastCredentials,
    SystemPodcastCredentialStore,
    parse_feed_input,
)
from iOpenPod.app.podcasts.errors import PodcastFeedError
from iOpenPod.app.podcasts.identity import subscription_identity

URL = "https://publisher.test/feed"
LOGIN = PodcastCredentials("tony@example.test", "p@ss:%word+")


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[str, PodcastCredentials] = {}
        self.unavailable = False
        self.reads = 0

    def load(self, feed_url: str) -> PodcastCredentials | None:
        self.reads += 1
        if self.unavailable:
            raise PodcastFeedError("Vault unavailable")
        return self.values.get(feed_url)

    def save(self, feed_url: str, credentials: PodcastCredentials) -> None:
        if self.unavailable:
            raise PodcastFeedError("Vault unavailable")
        self.values[feed_url] = credentials

    def remove(self, feed_url: str) -> None:
        if self.unavailable:
            raise PodcastFeedError("Vault unavailable")
        self.values.pop(feed_url, None)


def test_userinfo_is_decoded_once_and_removed_before_identity() -> None:
    entered = parse_feed_input(
        "https://tony%40example.test:p%40ss%3A%25word+@PUBLISHER.test:443/feed#fragment"
    )
    assert entered.url == URL
    assert entered.credentials == LOGIN
    assert "tony" not in repr(entered)
    assert LOGIN.password not in repr(LOGIN)
    changed = parse_feed_input("https://different:password@publisher.test/feed")
    assert subscription_identity(entered.url, "Show") == subscription_identity(
        changed.url, "Show"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://tony:secret@publisher.test/feed",
        "https://tony@publisher.test/feed",
        "https://tony:%GG@publisher.test/feed",
        "https://tony:%FF@publisher.test/feed",
        "https://tony:%0Asecret@publisher.test/feed",
        "https://tony:secret@publisher.test:invalid/feed",
        "https://tony:secret@publisher.test/\nfeed",
    ],
)
def test_invalid_or_insecure_input_has_no_credentials_in_error(url: str) -> None:
    with pytest.raises(PodcastFeedError) as error:
        parse_feed_input(url)
    assert "tony" not in str(error.value)
    assert "secret" not in str(error.value)
    assert "publisher.test" not in str(error.value)


def test_remembered_login_survives_new_session_and_forget_removes_it() -> None:
    store = MemoryCredentials()
    access = PodcastAccess(store)
    access.save(URL, LOGIN, remember=True)
    restarted = PodcastAccess(store)
    assert restarted.load(URL) == LOGIN
    assert restarted.load(URL + "-other") is None
    restarted.forget(URL)
    assert restarted.load(URL) is None


def test_session_login_works_without_vault_and_is_released() -> None:
    store = MemoryCredentials()
    store.unavailable = True
    access = PodcastAccess(store)
    access.save(URL, LOGIN, remember=False)
    assert access.load(URL) == LOGIN
    assert store.reads == 0
    assert not store.values
    access.clear_session()
    with pytest.raises(PodcastFeedError, match="Vault unavailable"):
        access.load(URL)


def test_failed_remember_does_not_replace_working_session() -> None:
    store = MemoryCredentials()
    access = PodcastAccess(store)
    access.save(URL, LOGIN, remember=False)
    store.unavailable = True
    with pytest.raises(PodcastFeedError):
        access.save(URL, PodcastCredentials("new", "secret"), remember=True)
    assert access.load(URL) == LOGIN


class _Vault:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[service, username] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.values[service, username]


def test_native_vault_round_trip_uses_opaque_feed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _Vault()
    monkeypatch.setattr(module, "native_credential_vault", lambda: vault)
    store = SystemPodcastCredentialStore()
    assert store.load(URL) is None
    store.save(URL, LOGIN)
    assert store.load(URL) == LOGIN
    (service, key), raw = next(iter(vault.values.items()))
    assert service == "iOpenPod 2 Podcast Logins"
    assert len(key) == 64
    assert "publisher" not in key
    assert json.loads(raw) == {"username": LOGIN.username, "password": LOGIN.password}
    store.remove(URL)
    assert store.load(URL) is None


def test_native_vault_failure_does_not_echo_backend_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise RuntimeError(LOGIN.password)

    monkeypatch.setattr(module, "native_credential_vault", unavailable)
    with pytest.raises(PodcastFeedError) as error:
        SystemPodcastCredentialStore().save(URL, LOGIN)
    assert LOGIN.password not in str(error.value)
