"""Exercise real urllib redirect/error handlers against an in-memory HTTPS peer."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import replace
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.request import BaseHandler, OpenerDirector, Request, build_opener
from urllib.response import addinfourl

import pytest
from PIL import Image
from tests.iOpenPod.app.podcasts.test_credentials import LOGIN, URL, MemoryCredentials

from iOpenPod.app.podcasts import http_client
from iOpenPod.app.podcasts.chapter_artwork import fetch_chapter_images
from iOpenPod.app.podcasts.credentials import PodcastAccess, PodcastCredentials
from iOpenPod.app.podcasts.documents import encode_subscriptions
from iOpenPod.app.podcasts.errors import (
    PodcastAccessError,
    PodcastAccessFailure,
    PodcastFeedError,
)
from iOpenPod.app.podcasts.feed_client import (
    FeedparserPodcastClient,
    HttpPodcastArtworkLoader,
)
from iOpenPod.app.podcasts.media import download_episode, episode_track
from iOpenPod.app.podcasts.models import PodcastArtworkRequest
from iOpenPod.app.podcasts.sync import PodcastEpisodeAddition

AUTH = (
    "Basic " + base64.b64encode(f"{LOGIN.username}:{LOGIN.password}".encode()).decode()
)
FEED = b'<rss version="2.0"><channel><title>Private show</title><item><guid>episode</guid><title>Private episode</title><enclosure url="https://publisher.test/episode.mp3" type="audio/mpeg"/></item></channel></rss>'


class _Response(addinfourl):
    def __init__(
        self, url: str, status: int, payload: bytes, headers: dict[str, str]
    ) -> None:
        message = Message()
        for name, value in headers.items():
            message[name] = value
        message["Content-Length"] = str(len(payload))
        super().__init__(BytesIO(payload), message, url, status)
        self.msg = "A server reason must never be shown: " + LOGIN.password


Route = Callable[[Request], tuple[int, bytes, dict[str, str]]]


class _Server(BaseHandler):
    handler_order = 100

    def __init__(self, route: Route) -> None:
        super().__init__()
        self.route = route
        self.requests: list[Request] = []

    def https_open(self, request: Request) -> _Response:
        self.requests.append(request)
        status, payload, headers = self.route(request)
        return _Response(request.full_url, status, payload, headers)


def serve(monkeypatch: pytest.MonkeyPatch, route: Route) -> _Server:
    server = _Server(route)

    def open_with_server(*handlers: BaseHandler | type[BaseHandler]) -> OpenerDirector:
        return build_opener(server, *handlers)

    monkeypatch.setattr(http_client, "build_opener", open_with_server)
    return server


def protected(request: Request) -> tuple[int, bytes, dict[str, str]]:
    if request.get_header("Authorization") != AUTH:
        return (
            401,
            b"private failure body",
            {"WWW-Authenticate": 'Basic realm="members"'},
        )
    return 200, FEED if request.full_url == URL else b"episode bytes", {}


def test_saved_login_authenticates_feed_and_media_without_leaking_into_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = serve(monkeypatch, protected)
    store = MemoryCredentials()
    PodcastAccess(store).save(URL, LOGIN, remember=True)
    access = PodcastAccess(store)
    show = FeedparserPodcastClient(access=access).fetch(URL)
    addition = PodcastEpisodeAddition(show, show.episodes[0])
    with download_episode(addition, checkpoint=lambda: None, access=access) as path:
        assert Path(path).read_bytes() == b"episode bytes"
    assert [request.get_header("Authorization") for request in server.requests] == [
        None,
        AUTH,
        None,
        AUTH,
    ]
    serialized = encode_subscriptions((show,))
    assert LOGIN.username.encode() not in serialized
    assert LOGIN.password.encode() not in serialized
    assert AUTH.encode() not in serialized
    assert episode_track(addition).metadata.podcast_rss_url == URL


@pytest.mark.parametrize(
    "destination",
    [
        "https://publisher.test/other",
        "https://cdn.test/episode.mp3",
        "https://publisher.test:444/episode.mp3",
        "https://publisher.test:0/episode.mp3",
        "https://www.publisher.test/episode.mp3",
    ],
)
def test_redirect_only_carries_login_to_exact_origin(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    def route(request: Request) -> tuple[int, bytes, dict[str, str]]:
        if request.full_url == URL:
            return 302, b"", {"Location": destination}
        return 200, b"ok", {}

    server = serve(monkeypatch, route)
    with http_client.open_podcast_request(
        Request(URL), timeout=1, feed_url=URL, credentials=LOGIN
    ) as response:
        assert response.read() == b"ok"
    assert server.requests[0].get_header("Authorization") == AUTH
    assert server.requests[1].get_header("Authorization") == (
        AUTH if destination == "https://publisher.test/other" else None
    )


@pytest.mark.parametrize(
    "destination",
    [
        "http://publisher.test/feed",
        "file:///private",
        "https://u:p@publisher.test/feed",
    ],
)
def test_unsafe_redirect_is_rejected_before_target_request(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    server = serve(monkeypatch, lambda _request: (302, b"", {"Location": destination}))
    with pytest.raises(PodcastFeedError):
        http_client.open_podcast_request(
            Request(URL), timeout=1, feed_url=URL, credentials=LOGIN
        )
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "status,challenge,login,reason",
    [
        (401, 'Basic realm="members"', None, PodcastAccessFailure.REQUIRED),
        (
            401,
            'Basic realm="members"',
            PodcastCredentials("wrong", "bad"),
            PodcastAccessFailure.REJECTED,
        ),
        (401, 'Bearer realm="members"', None, PodcastAccessFailure.UNSUPPORTED),
        (403, "", None, PodcastAccessFailure.DENIED),
    ],
)
def test_access_errors_are_distinct_bounded_and_do_not_echo_server_data(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    challenge: str,
    login: PodcastCredentials | None,
    reason: PodcastAccessFailure,
) -> None:
    server = serve(
        monkeypatch,
        lambda _request: (
            status,
            LOGIN.password.encode(),
            {"WWW-Authenticate": challenge},
        ),
    )
    with pytest.raises(PodcastAccessError) as error:
        http_client.open_podcast_request(
            Request(URL),
            timeout=1,
            feed_url=URL,
            access=PodcastAccess(MemoryCredentials()),
            credentials=login,
        )
    assert error.value.reason is reason
    assert LOGIN.password not in str(error.value)
    assert len(server.requests) == 1


def test_foreign_enclosure_cannot_challenge_for_feed_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = serve(monkeypatch, protected)
    store = MemoryCredentials()
    store.save(URL, LOGIN)
    with pytest.raises(PodcastAccessError) as error:
        http_client.open_podcast_request(
            Request("https://cdn.test/audio"),
            timeout=1,
            feed_url=URL,
            access=PodcastAccess(store),
        )
    assert error.value.reason is PodcastAccessFailure.DIFFERENT_SERVER
    assert store.reads == 0
    assert server.requests[0].get_header("Authorization") is None


def test_public_feed_does_not_access_unavailable_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, lambda _request: (200, FEED, {}))
    store = MemoryCredentials()
    store.unavailable = True
    assert (
        FeedparserPodcastClient(access=PodcastAccess(store)).fetch(URL).title
        == "Private show"
    )
    assert store.reads == 0


def test_wrong_saved_login_is_tried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    server = serve(monkeypatch, protected)
    store = MemoryCredentials()
    store.save(URL, replace(LOGIN, password="wrong"))
    with pytest.raises(PodcastAccessError) as error:
        FeedparserPodcastClient(access=PodcastAccess(store)).fetch(URL)
    assert error.value.reason is PodcastAccessFailure.REJECTED
    assert len(server.requests) == 2


def test_protected_artwork_and_chapter_documents_use_owning_feed_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = BytesIO()
    Image.new("RGB", (2, 2), "red").save(pixels, format="PNG")

    def route(request: Request) -> tuple[int, bytes, dict[str, str]]:
        if request.get_header("Authorization") != AUTH:
            return 401, b"", {"WWW-Authenticate": 'Basic realm="members"'}
        if request.full_url.endswith(".json"):
            return (
                200,
                b'{"version":"1.2.0","chapters":[{"startTime":1,"img":"cover.png"}]}',
                {},
            )
        return 200, pixels.getvalue(), {}

    serve(monkeypatch, route)
    store = MemoryCredentials()
    access = PodcastAccess(store)
    access.save(URL, LOGIN, remember=True)
    images = fetch_chapter_images(
        "https://publisher.test/chapters.json",
        checkpoint=lambda: None,
        feed_url=URL,
        access=access,
    )
    assert len(images) == 1 and images[0].display_time_ms == 1000
    loader = HttpPodcastArtworkLoader(access=access)
    result = loader.load_artwork(
        PodcastArtworkRequest(images[0].source_url, 2, feed_url=URL)
    )
    assert result is not None and result.rgb888 == b"\xff\x00\x00" * 4
    with pytest.raises(PodcastAccessError):
        loader.load_artwork(
            PodcastArtworkRequest(images[0].source_url, 2, feed_url=URL + "-another")
        )
