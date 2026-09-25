"""Async and cache behavior for remote Podcast cover artwork."""

from __future__ import annotations

import time

from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController
from iOpenPod.app.podcasts.models import PodcastArtworkImage, PodcastArtworkRequest


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
