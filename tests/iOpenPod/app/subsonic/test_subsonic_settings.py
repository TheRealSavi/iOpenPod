"""Tests for Subsonic settings definitions and keyring password store."""


import pytest

from iOpenPod.app.subsonic.settings import (
    SUBSONIC_PLAYLIST_IDS,
    SUBSONIC_PLAYLIST_MAPPINGS,
    SUBSONIC_SERVICE_KEY,
    SUBSONIC_URL,
    SUBSONIC_USERNAME,
    delete_subsonic_password,
    get_subsonic_password,
    set_subsonic_password,
)


def test_settings_definitions_defaults() -> None:
    assert SUBSONIC_URL.default == ""
    assert SUBSONIC_USERNAME.default == ""
    assert SUBSONIC_PLAYLIST_IDS.default == ()
    assert SUBSONIC_PLAYLIST_MAPPINGS.default == {}


def test_keyring_password_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    passwords: dict[tuple[str, str], str] = {}

    def mock_get(service: str, username: str) -> str | None:
        return passwords.get((service, username))

    def mock_set(service: str, username: str, password: str) -> None:
        passwords[(service, username)] = password

    def mock_delete(service: str, username: str) -> None:
        passwords.pop((service, username), None)

    monkeypatch.setattr("keyring.get_password", mock_get)
    monkeypatch.setattr("keyring.set_password", mock_set)
    monkeypatch.setattr("keyring.delete_password", mock_delete)

    # Empty user returns empty
    assert get_subsonic_password("") == ""

    # Set password
    set_subsonic_password("alice", "mypassword123")
    assert get_subsonic_password("alice") == "mypassword123"
    assert passwords[(SUBSONIC_SERVICE_KEY, "alice")] == "mypassword123"

    # Setting empty password deletes it
    set_subsonic_password("alice", "")
    assert get_subsonic_password("alice") == ""

    # Delete password
    set_subsonic_password("bob", "secret")
    delete_subsonic_password("bob")
    assert get_subsonic_password("bob") == ""
