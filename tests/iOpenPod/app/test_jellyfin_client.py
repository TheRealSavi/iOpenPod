"""Jellyfin HTTP contract: version gate, sign-in, paging, and play count updates."""

from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

import pytest

from iOpenPod.app.jellyfin.client import JellyfinClient, normalize_server_url
from iOpenPod.app.jellyfin.models import JellyfinAccount, JellyfinError

USER = "0123456789abcdef0123456789abcdef"
SERVER = "http://jellyfin.local:8096"


def item(
    item_id: str,
    title: str,
    *,
    album: str = "",
    artists: tuple[str, ...] = (),
    count: int = 0,
    length_ms: int = 1000,
    number: int | None = None,
) -> dict[str, object]:
    return {
        "Id": item_id,
        "Name": title,
        "Album": album,
        "Artists": list(artists),
        "AlbumArtist": "",
        "IndexNumber": number,
        "RunTimeTicks": length_ms * 10_000,
        "UserData": {"PlayCount": count},
    }


class FakeJellyfin:
    """The subset of the Jellyfin API the client uses, answered in memory."""

    def __init__(
        self,
        items: list[dict[str, object]] | None = None,
        *,
        version: str = "10.10.7",
    ) -> None:
        self.items = {str(entry["Id"]): entry for entry in items or ()}
        self.version = version
        self.requests: list[tuple[str, str, dict[str, object] | None, str]] = []
        self.fail_updates = False

    def count(self, item_id: str) -> object:
        user_data = self.items[item_id]["UserData"]
        assert isinstance(user_data, dict)
        return user_data["PlayCount"]

    def request(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None,
        headers: Mapping[str, str],
    ) -> object:
        self.requests.append((method, url, body, headers["Authorization"]))
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if parts.path == "/System/Info/Public":
            return {"Version": self.version, "Id": "server-1"}
        if parts.path == "/Users/AuthenticateByName":
            if body != {"Username": "alice", "Pw": "secret"}:
                raise JellyfinError("refused")
            return {"AccessToken": "token-1", "User": {"Id": USER, "Name": "alice"}}
        if parts.path == "/Items":
            start, limit = int(query["startIndex"][0]), int(query["limit"][0])
            values = list(self.items.values())
            return {
                "Items": values[start : start + limit],
                "TotalRecordCount": len(values),
            }
        if parts.path.startswith("/UserItems/"):
            if self.fail_updates:
                raise JellyfinError("Could not reach the Jellyfin server.")
            assert body is not None
            item_id = parts.path.split("/")[2]
            self.items[item_id]["UserData"] = {"PlayCount": body["PlayCount"]}
            return {"PlayCount": body["PlayCount"], "Played": True}
        raise AssertionError(url)


def account() -> JellyfinAccount:
    return JellyfinAccount(SERVER, "server-1", USER, "alice", "device-1", "token-1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.168.1.20:8096", "http://192.168.1.20:8096"),
        (" http://192.168.1.20:8096/ ", "http://192.168.1.20:8096"),
        ("https://media.example/jellyfin/", "https://media.example/jellyfin"),
    ],
)
def test_server_address_is_normalized(value: str, expected: str) -> None:
    assert normalize_server_url(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "ftp://host", "http://user:pw@host", "http://host:99999", "http://host?x=1"],
)
def test_invalid_server_address_is_rejected(value: str) -> None:
    with pytest.raises(JellyfinError, match="server address"):
        normalize_server_url(value)


def test_connect_exchanges_password_for_token_without_sending_a_token() -> None:
    server = FakeJellyfin()
    connected = JellyfinClient(server).connect(
        "jellyfin.local:8096", "alice", "secret", "device-1"
    )
    assert connected == account()
    assert "secret" not in repr(connected) and "token-1" not in repr(connected)
    assert [request[0] for request in server.requests] == ["GET", "POST"]
    assert all("Token=" not in request[3] for request in server.requests)
    assert 'DeviceId="device-1"' in server.requests[1][3]


def test_servers_older_than_10_9_are_refused_before_sign_in() -> None:
    server = FakeJellyfin(version="10.8.13")
    with pytest.raises(JellyfinError, match=r"10\.9 or later"):
        JellyfinClient(server).connect(SERVER, "alice", "secret", "device-1")
    assert len(server.requests) == 1


def test_tracks_are_paged_with_the_token_and_read_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("iOpenPod.app.jellyfin.client.PAGE_SIZE", 2)
    server = FakeJellyfin(
        [
            item(f"{index:032x}", f"Song {index}", count=index, number=index)
            for index in range(1, 6)
        ]
    )
    checks: list[None] = []
    tracks = JellyfinClient(server).tracks(account(), lambda: checks.append(None))
    assert [track.title for track in tracks] == [f"Song {i}" for i in range(1, 6)]
    assert tracks[2].play_count == 3 and tracks[2].track_number == 3
    assert tracks[0].length_ms == 1000
    assert len(server.requests) == len(checks) == 3
    assert all('Token="token-1"' in request[3] for request in server.requests)


def test_malformed_library_response_is_reported() -> None:
    server = FakeJellyfin([{"Id": "not-an-id", "Name": "Song"}])
    with pytest.raises(JellyfinError, match="unexpected music library"):
        JellyfinClient(server).tracks(account(), lambda: None)


def test_set_play_count_posts_user_data_for_the_signed_in_user() -> None:
    item_id = "a" * 32
    server = FakeJellyfin([item(item_id, "Song")])
    JellyfinClient(server).set_play_count(account(), item_id, 7)
    method, url, body, _ = server.requests[0]
    assert method == "POST"
    assert url == f"{SERVER}/UserItems/{item_id}/UserData?userId={USER}"
    assert body == {"PlayCount": 7, "Played": True}
    assert server.count(item_id) == 7


@pytest.mark.parametrize(("item_id", "count"), [("../x", 1), ("a" * 32, 0)])
def test_invalid_updates_are_refused_without_a_request(
    item_id: str, count: int
) -> None:
    server = FakeJellyfin()
    with pytest.raises(JellyfinError):
        JellyfinClient(server).set_play_count(account(), item_id, count)
    assert not server.requests


def test_only_the_jellyfin_12_authorization_header_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "iOpenPod.app.jellyfin.client.get_version", lambda: "2.1.0.dev1+g1a2b"
    )
    item_id = "a" * 32
    server = FakeJellyfin([item(item_id, "Song")])
    headers: list[dict[str, str]] = []
    original = server.request

    def capture(
        method: str,
        url: str,
        body: dict[str, object] | None,
        sent: Mapping[str, str],
    ) -> object:
        headers.append(dict(sent))
        return original(method, url, body, sent)

    monkeypatch.setattr(server, "request", capture)
    client = JellyfinClient(server)
    client.connect(SERVER, "alice", "secret", "device-1")
    client.tracks(account(), lambda: None)
    client.set_play_count(account(), item_id, 2)
    assert all(set(sent) == {"Authorization"} for sent in headers)
    assert all(sent["Authorization"].startswith("MediaBrowser ") for sent in headers)
    # The server URL-decodes values, so "+" must not reach it unencoded.
    assert all(
        'Version="2.1.0.dev1%2Bg1a2b"' in sent["Authorization"] for sent in headers
    )
    assert all(
        "api_key" not in url.lower() and "/emby/" not in url.lower()
        for _, url, _, _ in server.requests
    )
