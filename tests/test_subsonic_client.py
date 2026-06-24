from __future__ import annotations

import hashlib
import os

import pytest

from SubsonicManager import client as client_mod
from SubsonicManager.client import SubsonicClient, SubsonicConnectionError


class _JsonResponse:
    """Minimal stand-in for a requests json() response."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.content = b""

    def json(self) -> dict:
        return self._payload


class _BytesResponse:
    """Stand-in for a binary response (getCoverArt / download)."""

    def __init__(self, content: bytes, headers: dict | None = None, status: int = 200) -> None:
        self.content = content
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _StreamResponse(_BytesResponse):
    def __init__(self, content: bytes, headers: dict | None = None) -> None:
        super().__init__(content, headers)
        self._chunks = [content[i : i + 16] for i in range(0, len(content), 16)]

    def iter_content(self, chunk_size: int = 16):
        yield from self._chunks

    def raise_for_status(self) -> None:
        pass


def _ok(extra: dict | None = None) -> dict:
    return {"subsonic-response": {"status": "ok", **(extra or {})}}


def _failed(code: int, message: str) -> dict:
    return {"subsonic-response": {"status": "failed", "error": {"code": code, "message": message}}}


# ---------------------------------------------------------------------------
# auth / URL building
# ---------------------------------------------------------------------------


def test_token_is_hex_md5_of_password_plus_salt() -> None:
    salt = "abc123"
    token = client_mod._make_token("hunter2", salt)
    assert token == hashlib.md5(b"hunter2abc123").hexdigest()


def test_endpoint_url_carries_token_salt_and_json_format() -> None:
    c = SubsonicClient("https://music.test/", "bob", "pw")
    url = c._endpoint_url("ping")
    assert url.startswith("https://music.test/rest/ping.view?")
    assert "u=bob" in url
    assert "f=json" in url
    assert "&c=iOpenPod" in url
    assert "&t=" in url
    assert "&s=" in url


def test_normalize_server_url_strips_trailing_slash() -> None:
    assert client_mod._normalize_server_url("https://x.test/") == "https://x.test"
    assert client_mod._normalize_server_url("https://x.test") == "https://x.test"


# ---------------------------------------------------------------------------
# ping / error handling
# ---------------------------------------------------------------------------


def test_ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(_ok()))
    c.ping()  # no raise


def test_ping_failed_raises_connection_error_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "wrong")
    monkeypatch.setattr(
        client_mod.requests, "get", lambda *a, **k: _JsonResponse(_failed(40, "Wrong username or password"))
    )
    with pytest.raises(SubsonicConnectionError) as exc_info:
        c.ping()
    assert exc_info.value.error_code == 40
    assert "Wrong username or password" in str(exc_info.value)
    assert exc_info.value.url == "https://music.test"


def test_non_json_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")

    class NotJson:
        status_code = 302

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: NotJson())
    with pytest.raises(SubsonicConnectionError):
        c.ping()


def test_network_error_raises_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests as real_requests

    c = SubsonicClient("https://music.test", "bob", "pw")

    def boom(*a, **k):
        raise real_requests.ConnectionError("down")

    monkeypatch.setattr(client_mod.requests, "get", boom)
    with pytest.raises(SubsonicConnectionError) as exc_info:
        c.ping()
    assert "Could not reach" in str(exc_info.value)


# ---------------------------------------------------------------------------
# catalog endpoints
# ---------------------------------------------------------------------------


def test_get_starred2_returns_inner_object(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    body = _ok({"starred2": {"song": [{"id": "s1"}], "album": []}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(body))
    assert c.get_starred2() == {"song": [{"id": "s1"}], "album": []}


def test_get_playlists_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    body = _ok({"playlists": {"playlist": [{"id": "p1", "name": "Faves"}]}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(body))
    assert c.get_playlists() == [{"id": "p1", "name": "Faves"}]


def test_get_playlists_empty_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(_ok()))
    assert c.get_playlists() == []


def test_get_playlist_returns_with_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    body = _ok({"playlist": {"id": "p1", "entry": [{"id": "s1"}]}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(body))
    pl = c.get_playlist("p1")
    assert pl["entry"] == [{"id": "s1"}]


def test_get_album_returns_with_songs(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    body = _ok({"album": {"id": "a1", "song": [{"id": "s1"}]}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: _JsonResponse(body))
    album = c.get_album("a1")
    assert album["song"] == [{"id": "s1"}]


# ---------------------------------------------------------------------------
# cover art + download
# ---------------------------------------------------------------------------


def test_get_cover_art_bytes_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    monkeypatch.setattr(
        client_mod.requests, "get", lambda *a, **k: _BytesResponse(b"\x89PNGfake")
    )
    assert c.get_cover_art_bytes("cov1") == b"\x89PNGfake"


def test_download_skips_when_dest_exists(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    dest = tmp_path / "track.mp3"
    dest.write_bytes(b"already here")

    called = {"n": 0}

    def fake_get(*a, **k):
        called["n"] += 1
        return _StreamResponse(b"should not be used")

    monkeypatch.setattr(client_mod.requests, "get", fake_get)
    result = c.download_track("t1", str(dest))
    assert result == str(dest)
    assert called["n"] == 0  # no network call


def test_download_streams_to_dest_and_reports_progress(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    dest = tmp_path / "track.mp3"
    payload = bytes(range(64))  # 64 bytes, will be chunked into 16-byte pieces

    monkeypatch.setattr(
        client_mod.requests,
        "get",
        lambda *a, **k: _StreamResponse(payload, headers={"Content-Length": str(len(payload))}),
    )

    seen: list[tuple[int, int]] = []
    result = c.download_track("t1", str(dest), progress_cb=lambda d, t: seen.append((d, t)))

    assert result == str(dest)
    assert os.path.exists(dest)
    assert dest.read_bytes() == payload
    # final progress callback reports total downloaded and full content-length
    assert seen and seen[-1] == (64, 64)


def test_download_cancels_and_leaves_no_partial(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    dest = tmp_path / "track.mp3"
    payload = bytes(range(64))

    monkeypatch.setattr(
        client_mod.requests, "get", lambda *a, **k: _StreamResponse(payload)
    )

    class Cancelled:
        def is_cancelled(self) -> bool:
            return True

    with pytest.raises(RuntimeError, match="cancelled"):
        c.download_track("t1", str(dest), cancel_token=Cancelled())

    assert not dest.exists()
    # no .part left behind
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())


def test_download_cleans_up_part_on_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = SubsonicClient("https://music.test", "bob", "pw")
    dest = tmp_path / "track.mp3"
    import requests as real_requests

    def boom(*a, **k):
        raise real_requests.ConnectionError("boom")

    monkeypatch.setattr(client_mod.requests, "get", boom)
    with pytest.raises(SubsonicConnectionError):
        c.download_track("t1", str(dest))
    assert not dest.exists()
