"""Publisher covers stay bounded and cancellation stops their preparation."""

from dataclasses import dataclass, field
from threading import Event

import pytest

from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.podcasts import sync_artwork
from iOpenPod.app.podcasts.models import (
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastSubscription,
    SubscriptionSource,
)
from iPodDB.library import IssueSeverity


@dataclass
class _Loader:
    cancel_after_load: Event | None = None
    requests: list[PodcastArtworkRequest] = field(
        default_factory=list[PodcastArtworkRequest]
    )

    def load_artwork(self, request: PodcastArtworkRequest) -> PodcastArtworkImage:
        self.requests.append(request)
        if self.cancel_after_load is not None:
            self.cancel_after_load.set()
        return PodcastArtworkImage(
            request.source_url,
            request.source_url,
            2,
            2,
            b"\xff\x00\x00" * 4,
        )


def _subscription(identity: str, cover: str) -> PodcastSubscription:
    return PodcastSubscription(
        identity,
        f"https://publisher.example/{identity}.xml",
        identity,
        SubscriptionSource.USER,
        artwork_url=cover,
    )


def test_shared_publisher_cover_fits_once_in_bounded_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_artwork, "_MAX_BATCH_BYTES", 12)
    loader = _Loader()
    cover_url = "https://publisher.example/shared.png"
    result = sync_artwork.prepare_podcast_covers(
        (
            _subscription("first", cover_url),
            _subscription("second", cover_url),
            _subscription("no-art", ""),
            _subscription("over-budget", "https://publisher.example/other.png"),
        ),
        128,
        checkpoint=lambda: None,
        progress=lambda _: None,
        loader=loader,
    )

    assert [cover.subscription_id for cover in result.covers] == ["first", "second"]
    assert result.covers[0].pixels is result.covers[1].pixels
    assert len(loader.requests) == 2
    assert len(result.issues) == 1
    assert result.issues[0].severity is IssueSeverity.WARNING
    assert result.issues[0].artifact == "https://publisher.example/other.png"
    assert "preparation limit" in result.issues[0].detail


def test_cancellation_after_cover_download_stops_preparation() -> None:
    cancelled = Event()
    loader = _Loader(cancel_after_load=cancelled)

    def checkpoint() -> None:
        if cancelled.is_set():
            raise PreparationCancelledError

    with pytest.raises(PreparationCancelledError):
        sync_artwork.prepare_podcast_covers(
            (_subscription("show", "https://publisher.example/cover.png"),),
            128,
            checkpoint=checkpoint,
            progress=lambda _: None,
            loader=loader,
        )
    assert len(loader.requests) == 1
