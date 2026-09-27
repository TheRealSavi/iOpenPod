import json
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from threading import Event
from types import TracebackType
from typing import Self
from urllib.request import Request

import pytest
from PIL import Image

from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.podcasts import feed_client
from iOpenPod.app.podcasts.feed_client import (
    ApplePodcastDirectoryClient,
    FeedparserPodcastClient,
    HttpPodcastArtworkLoader,
    PodcastFeedError,
)
from iOpenPod.app.podcasts.models import (
    PodcastArtworkRequest,
    PodcastSearchResult,
    PodcastSubscription,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.sync_artwork import prepare_podcast_covers


def test_directory_retains_text_and_feed_url_without_promotional_artwork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "results": [
                {
                    "collectionName": "Example Show",
                    "artistName": "Example Network",
                    "feedUrl": "https://example.test/feed",
                    "artworkUrl600": "https://apple-cdn.example.test/large.jpg",
                    "artworkUrl100": "https://apple-cdn.example.test/small.jpg",
                    "primaryGenreName": "Technology",
                    "trackCount": 42,
                }
            ]
        }
    ).encode()

    def request_bytes(
        url: str,
        *,
        limit: int,
        timeout_seconds: int,
        accept: str,
    ) -> tuple[bytes, str]:
        del limit, timeout_seconds
        assert url.startswith("https://itunes.apple.com/search?")
        assert "term=Example+Show" in url
        assert accept == "application/json"
        return payload, url

    monkeypatch.setattr(feed_client, "_request_bytes", request_bytes)

    results = ApplePodcastDirectoryClient().search("Example Show")

    assert results == (
        PodcastSearchResult(
            "Example Show",
            "Example Network",
            "https://example.test/feed",
            category="Technology",
            episode_count=42,
        ),
    )
    assert not hasattr(results[0], "artwork_url")


def test_feedparser_client_normalizes_typed_podcast_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <title>Example Show</title>
            <description>&lt;b&gt;Useful&lt;/b&gt; notes</description>
            <itunes:author>Example Network</itunes:author>
            <itunes:image href="https://publisher.example.test/cover.png" />
            <item>
              <guid>guid-1</guid>
              <title>Episode One</title>
              <description>&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;</description>
              <pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate>
              <itunes:duration>1:02:03</itunes:duration>
              <itunes:episode>8</itunes:episode>
              <enclosure url="https://cdn.example.test/one.mp3" length="1234" type="audio/mpeg" />
            </item>
          </channel>
        </rss>
        """
    ).encode()

    def request_bytes(
        url: str,
        *,
        limit: int,
        timeout_seconds: int,
        accept: str,
    ) -> tuple[bytes, str]:
        del url, limit, timeout_seconds, accept
        return payload, "https://example.test/feed"

    monkeypatch.setattr(feed_client, "_request_bytes", request_bytes)

    subscription = FeedparserPodcastClient().fetch("https://example.test/feed")

    assert subscription.title == "Example Show"
    assert subscription.author == "Example Network"
    assert subscription.description == "Useful notes"
    assert subscription.artwork_url == "https://publisher.example.test/cover.png"
    episode = subscription.episodes[0]
    assert episode.title == "Episode One"
    assert episode.description == "Hello & welcome"
    assert episode.duration_seconds == 3723
    assert episode.episode_number == 8
    assert episode.size_bytes == 1234
    assert episode.enclosure_url == "https://cdn.example.test/one.mp3"


def test_artwork_loader_returns_bounded_square_rgb_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = BytesIO()
    Image.new("RGBA", (240, 120), (22, 88, 144, 180)).save(payload, format="PNG")

    def request_bytes(
        url: str,
        *,
        limit: int,
        timeout_seconds: int,
        accept: str,
        checkpoint: Callable[[], None] | None = None,
    ) -> tuple[bytes, str]:
        del url, limit, timeout_seconds, accept, checkpoint
        return payload.getvalue(), "https://cdn.example.test/cover.png"

    monkeypatch.setattr(feed_client, "_request_bytes", request_bytes)

    image = HttpPodcastArtworkLoader().load_artwork(
        PodcastArtworkRequest("https://example.test/cover.png", 96)
    )

    assert image is not None
    assert image.source_url == "https://example.test/cover.png"
    assert image.width == 96
    assert image.height == 96
    assert len(image.rgb888) == 96 * 96 * 3


class _TrickleResponse:
    def __init__(
        self, content: bytes, after_read: Callable[[], None] | None = None
    ) -> None:
        self.content = BytesIO(content)
        self.after_read = after_read
        self.headers: dict[str, str] = {}
        self.consumed = 0
        self.elapsed = 0.0

    def geturl(self) -> str:
        return "https://example.test/cover.png"

    def monotonic(self) -> float:
        return self.elapsed

    def read(self, size: int) -> bytes:
        data = self.content.read(size)
        self.consumed += len(data)
        self.elapsed += 30
        if self.after_read is not None:
            self.after_read()
        return data

    def read1(self, size: int) -> bytes:
        return self.read(min(size, 1))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.content.close()


@dataclass(frozen=True)
class _OpenResponse:
    response: _TrickleResponse

    def __call__(self, request: Request, *, timeout: int) -> _TrickleResponse:
        assert request.full_url == self.response.geturl()
        assert timeout > 0
        return self.response


def _cover_bytes() -> bytes:
    payload = BytesIO()
    Image.new("RGB", (2, 2), "red").save(payload, format="PNG")
    return payload.getvalue()


def test_sync_cover_cancellation_interrupts_response_before_it_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = Event()
    response = _TrickleResponse(_cover_bytes(), cancelled.set)
    monkeypatch.setattr(feed_client, "urlopen", _OpenResponse(response))

    def checkpoint() -> None:
        if cancelled.is_set():
            raise PreparationCancelledError

    with pytest.raises(PreparationCancelledError):
        prepare_podcast_covers(
            (
                PodcastSubscription(
                    "show",
                    "https://example.test/feed",
                    "Show",
                    SubscriptionSource.USER,
                    artwork_url=response.geturl(),
                ),
            ),
            128,
            checkpoint=checkpoint,
            progress=lambda _: None,
        )

    assert response.consumed == 1, "Cancellation must interrupt a trickling body"
    assert response.content.closed


def test_trickling_cover_response_stops_at_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _TrickleResponse(_cover_bytes())
    monkeypatch.setattr(feed_client, "urlopen", _OpenResponse(response))
    monkeypatch.setattr(
        "iOpenPod.app.podcasts.feed_client.time.monotonic", response.monotonic
    )

    with pytest.raises(PodcastFeedError, match="deadline"):
        HttpPodcastArtworkLoader().load_artwork(
            PodcastArtworkRequest(response.geturl(), 128)
        )

    assert 0 < response.consumed < len(_cover_bytes())
    assert response.content.closed


def test_cover_response_limit_applies_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _TrickleResponse(b"a" * 100)
    monkeypatch.setattr(feed_client, "urlopen", _OpenResponse(response))
    monkeypatch.setattr(feed_client, "_ARTWORK_LIMIT", 16)

    with pytest.raises(PodcastFeedError, match="larger"):
        HttpPodcastArtworkLoader().load_artwork(
            PodcastArtworkRequest(response.geturl(), 128)
        )

    assert response.consumed == 17
    assert response.content.closed
