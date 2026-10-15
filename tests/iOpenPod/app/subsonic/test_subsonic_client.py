"""Tests for OpenSubsonic REST API client."""

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from iOpenPod.app.subsonic.client import (
    SubsonicClient,
    SubsonicConnectionError,
    _make_token,
    _normalize_server_url,
)
from iOpenPod.app.subsonic.models import SubsonicPlaylist, SubsonicSong


def test_url_normalization() -> None:
    assert _normalize_server_url("http://example.com/") == "http://example.com"
    assert _normalize_server_url("https://music.local:4533///") == "https://music.local:4533"
    assert _normalize_server_url("example.com") == "https://example.com"
    assert _normalize_server_url("") == ""


def test_token_generation() -> None:
    token = _make_token("secret", "salt123")
    assert isinstance(token, str)
    assert len(token) == 32


def test_client_auth_params() -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret123")
    params = client._auth_params()
    assert params["u"] == "alice"
    assert params["v"] == "1.16.1"
    assert params["c"] == "iOpenPod"
    assert params["f"] == "json"
    assert len(params["s"]) > 0
    assert len(params["t"]) == 32


def test_ping_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret")
    payload = {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    mock_resp = BytesIO(json.dumps(payload).encode("utf-8"))
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    client.ping()
    mock_opener.open.assert_called_once()


def test_ping_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SubsonicClient("https://music.example.com", "alice", "wrong")
    payload = {
        "subsonic-response": {
            "status": "failed",
            "error": {"code": 40, "message": "Wrong username or password"},
        }
    }
    mock_resp = BytesIO(json.dumps(payload).encode("utf-8"))
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    with pytest.raises(SubsonicConnectionError) as exc_info:
        client.ping()
    assert exc_info.value.error_code == 40
    assert "Wrong username or password" in str(exc_info.value)


def test_get_playlists_parsing() -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret")
    payload = {
        "subsonic-response": {
            "status": "ok",
            "playlists": {
                "playlist": [
                    {
                        "id": "pl-1",
                        "name": "Road Trip",
                        "comment": "Fast tracks",
                        "songCount": 25,
                        "duration": 5400,
                        "created": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": "pl-2",
                        "name": "Chill",
                        "songCount": 10,
                    },
                ]
            },
        }
    }
    mock_resp = BytesIO(json.dumps(payload).encode("utf-8"))
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    playlists = client.get_playlists()
    assert len(playlists) == 2
    assert playlists[0] == SubsonicPlaylist(
        playlist_id="pl-1",
        name="Road Trip",
        comment="Fast tracks",
        song_count=25,
        duration=5400,
        created="2026-01-01T00:00:00Z",
    )
    assert playlists[1].playlist_id == "pl-2"
    assert playlists[1].name == "Chill"


def test_get_playlist_entries() -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret")
    payload = {
        "subsonic-response": {
            "status": "ok",
            "playlist": {
                "id": "pl-1",
                "name": "My Favorites",
                "entry": [
                    {
                        "id": "s-100",
                        "title": "Song One",
                        "artist": "Artist A",
                        "album": "Album X",
                        "track": 3,
                        "year": 2024,
                        "genre": "Rock",
                        "duration": 210,
                        "coverArt": "al-50",
                    },
                    {
                        "id": "s-101",
                        "title": "Song Two",
                    },
                ],
            },
        }
    }
    mock_resp = BytesIO(json.dumps(payload).encode("utf-8"))
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    songs = client.get_playlist("pl-1")
    assert len(songs) == 2
    assert songs[0] == SubsonicSong(
        song_id="s-100",
        title="Song One",
        artist="Artist A",
        album="Album X",
        track=3,
        year=2024,
        genre="Rock",
        duration=210,
        cover_art="al-50",
    )
    assert songs[1].song_id == "s-101"
    assert songs[1].title == "Song Two"


def test_get_cover_art_bytes() -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret")
    data = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    mock_resp = BytesIO(data)
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    downloaded = client.get_cover_art_bytes("art-123")
    assert downloaded == data


def test_download_track(tmp_path: Path) -> None:
    client = SubsonicClient("https://music.example.com", "alice", "secret")
    audio_data = b"ID3\x03\x00\x00fakeaudiostreamingdata"
    mock_resp = BytesIO(audio_data)
    mock_opener = MagicMock()
    mock_opener.open.return_value.__enter__.return_value = mock_resp
    client._opener = mock_opener

    dest = tmp_path / "song.mp3"
    client.download_track("s-100", str(dest))
    assert dest.read_bytes() == audio_data
