"""Host-only Podcast logins, separate from portable Subscription documents."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit, urlunsplit

from iOpenPod.app.core.credential_vault import native_credential_vault
from iOpenPod.app.podcasts.errors import PodcastFeedError
from iOpenPod.app.podcasts.identity import normalize_feed_url

_SERVICE = "iOpenPod 2 Podcast Logins"


@dataclass(frozen=True, slots=True)
class PodcastCredentials:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise PodcastFeedError("Enter both a Podcast username and password.")
        if ":" in self.username or any(
            ord(char) < 32 or ord(char) == 127 for char in self.username + self.password
        ):
            raise PodcastFeedError("The Podcast login contains unsupported characters.")


@dataclass(frozen=True, slots=True)
class PodcastFeedInput:
    url: str
    credentials: PodcastCredentials | None = field(default=None, repr=False)


def parse_feed_input(value: str) -> PodcastFeedInput:
    """Extract userinfo once, before ordinary URL validation or identity hashing."""
    try:
        parsed = urlsplit(value.strip())
        # urlsplit silently drops some controls; reject them at the input boundary.
        if any(ord(char) < 32 or ord(char) == 127 for char in value.strip()):
            raise ValueError
        credentials = None
        if parsed.username is not None or parsed.password is not None:
            user, password = parsed.username or "", parsed.password or ""
            if re.search(r"%(?![0-9a-fA-F]{2})", user + password):
                raise ValueError
            credentials = PodcastCredentials(
                unquote(user, errors="strict"), unquote(password, errors="strict")
            )
        url = normalize_feed_url(
            urlunsplit(parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]))
        )
        if not url:
            raise ValueError
    except (ValueError, UnicodeError):
        raise PodcastFeedError(
            "Enter a valid HTTP or HTTPS podcast feed URL."
        ) from None
    if credentials is not None:
        require_secure_feed(url)
    return PodcastFeedInput(url, credentials)


def require_secure_feed(feed_url: str) -> str:
    normalized = normalize_feed_url(feed_url)
    if not normalized or urlsplit(normalized).scheme != "https":
        raise PodcastFeedError("Podcast logins require an HTTPS feed URL.")
    return normalized


class PodcastCredentialStore(Protocol):
    def load(self, feed_url: str) -> PodcastCredentials | None: ...
    def save(self, feed_url: str, credentials: PodcastCredentials) -> None: ...
    def remove(self, feed_url: str) -> None: ...


class SystemPodcastCredentialStore:
    @staticmethod
    def _key(feed_url: str) -> str:
        return hashlib.sha256(require_secure_feed(feed_url).encode()).hexdigest()

    def load(self, feed_url: str) -> PodcastCredentials | None:
        try:
            raw = native_credential_vault().get_password(_SERVICE, self._key(feed_url))
            if raw is None:
                return None
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            payload = cast("dict[object, object]", value)
            if set(payload) != {"username", "password"}:
                raise ValueError
            username, password = payload["username"], payload["password"]
            if not isinstance(username, str) or not isinstance(password, str):
                raise ValueError
            return PodcastCredentials(username, password)
        except Exception:
            raise PodcastFeedError(
                "Could not read the Podcast login. Unlock your OS credential store, or enter the login again without remembering it."
            ) from None

    def save(self, feed_url: str, credentials: PodcastCredentials) -> None:
        try:
            native_credential_vault().set_password(
                _SERVICE,
                self._key(feed_url),
                json.dumps(
                    {"username": credentials.username, "password": credentials.password}
                ),
            )
        except Exception:
            raise PodcastFeedError(
                "Could not save the Podcast login. Unlock your OS credential store, or turn off Remember on this computer and try again."
            ) from None

    def remove(self, feed_url: str) -> None:
        try:
            vault, key = native_credential_vault(), self._key(feed_url)
            if vault.get_password(_SERVICE, key) is not None:
                vault.delete_password(_SERVICE, key)
        except Exception:
            raise PodcastFeedError(
                "Could not remove the saved Podcast login. Unlock your OS credential store and try again."
            ) from None


class PodcastAccess:
    """One application-owned credential session, shared with all Podcast workers.

    Vault reads happen only after a server asks for authentication, so public
    Podcasts continue working on Hosts without a native vault.
    """

    def __init__(self, store: PodcastCredentialStore | None = None) -> None:
        self._store = store or SystemPodcastCredentialStore()
        self._session: dict[str, PodcastCredentials] = {}
        self._lock = RLock()

    def load(self, feed_url: str) -> PodcastCredentials | None:
        key = require_secure_feed(feed_url)
        with self._lock:
            value = self._session.get(key)
            if value is None:
                value = self._store.load(key)
                if value is not None:
                    self._session[key] = value
            return value

    def save(
        self, feed_url: str, credentials: PodcastCredentials, *, remember: bool
    ) -> None:
        key = require_secure_feed(feed_url)
        with self._lock:
            if remember:
                self._store.save(key, credentials)
            # Session-only entry deliberately does not touch a locked vault.
            # Forget Login is the explicit action for removing an older saved login.
            self._session[key] = credentials

    def forget(self, feed_url: str) -> None:
        key = require_secure_feed(feed_url)
        with self._lock:
            self._store.remove(key)
            self._session.pop(key, None)

    def clear_session(self) -> None:
        with self._lock:
            self._session.clear()
