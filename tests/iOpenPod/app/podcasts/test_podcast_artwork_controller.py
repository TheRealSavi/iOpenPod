"""Async and cache behavior for remote Podcast cover artwork."""

from __future__ import annotations

import time

import pytest
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController
from iOpenPod.app.podcasts.models import (
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastSubscription,
    SubscriptionSource,
)


class _Loader:
    def __init__(self) -> None:
        self.requests: list[PodcastArtworkRequest] = []

    def load_artwork(self, request: PodcastArtworkRequest) -> PodcastArtworkImage:
        self.requests.append(request)
        size = request.target_px
        return PodcastArtworkImage(
            cache_key=f"cover/{size}",
            source_url=request.source_url,
            width=size,
            height=size,
            rgb888=bytes((20, 80, 140)) * size * size,
        )


def test_podcast_artwork_controller_deduplicates_and_caches_visible_request() -> None:
    loader = _Loader()
    controller = PodcastArtworkController(loader)
    received: list[PodcastArtworkImage] = []
    controller.artworkReady.connect(received.append)

    try:
        assert controller.request("https://example.test/cover.png", 48) is None
        assert controller.request("https://example.test/cover.png", 48) is None

        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(10)

        assert len(received) == 1
        assert loader.requests == [
            PodcastArtworkRequest("https://example.test/cover.png", 48)
        ]
        assert controller.request("https://example.test/cover.png", 48) == received[0]
    finally:
        controller.shutdown()


class _Feeds:
    def __init__(self, *, missing: bool = False, fail: bool = False) -> None:
        self.requests: list[str] = []
        self.missing = missing
        self.fail = fail

    def fetch(self, feed_url: str) -> PodcastSubscription:
        self.requests.append(feed_url)
        if self.fail:
            raise OSError("Publisher unavailable")
        return PodcastSubscription(
            "show",
            feed_url,
            "Show",
            SubscriptionSource.USER,
            artwork_url="" if self.missing else "https://publisher.test/cover.jpg",
        )


def _finish(controller: PodcastArtworkController) -> None:
    deadline = time.monotonic() + 2
    while controller.pending_count and time.monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    assert not controller.pending_count


def test_discovery_resolves_only_requested_publisher_covers_and_reuses_pixels() -> None:
    feeds, loader = _Feeds(), _Loader()
    controller = PodcastArtworkController(loader, feed_client=feeds)
    changed: list[str] = []
    controller.feedArtworkChanged.connect(changed.append)
    try:
        assert not feeds.requests
        assert controller.request_feed("https://publisher.test/rss", 88) is None
        assert controller.request_feed("https://publisher.test/rss", 88) is None
        _finish(controller)
        image = controller.request_feed("https://publisher.test/rss", 88)
        assert image is not None
        assert image.source_url == "https://publisher.test/cover.jpg"
        assert feeds.requests == ["https://publisher.test/rss"]
        assert loader.requests == [PodcastArtworkRequest(image.source_url, 88)]
        assert changed == feeds.requests
        assert controller.cached_byte_count == 88 * 88 * 3
    finally:
        controller.shutdown()


@pytest.mark.parametrize("fail", (False, True))
def test_missing_discovery_cover_is_nonfatal_and_not_retried_per_paint(
    fail: bool,
) -> None:
    feeds, loader = _Feeds(missing=True, fail=fail), _Loader()
    controller = PodcastArtworkController(loader, feed_client=feeds)
    unavailable: list[str] = []
    controller.artworkUnavailable.connect(unavailable.append)
    try:
        controller.request_feed("https://publisher.test/rss", 88)
        _finish(controller)
        assert controller.request_feed("https://publisher.test/rss", 88) is None
        assert feeds.requests == unavailable == ["https://publisher.test/rss"]
        assert not loader.requests
    finally:
        controller.shutdown()
