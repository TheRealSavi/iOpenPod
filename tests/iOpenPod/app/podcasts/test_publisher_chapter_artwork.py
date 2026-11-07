"""Publisher chapter pictures are bounded and independent of native navigation."""

import json
from dataclasses import replace

import pytest

from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.podcasts import chapter_artwork, sync_artwork
from iOpenPod.app.podcasts.chapter_artwork import parse_chapter_images
from iOpenPod.app.podcasts.feed_client import PodcastFeedError
from iOpenPod.app.podcasts.models import (
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastChapterImage,
    PodcastEpisode,
    PodcastSubscription,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.sync_artwork import PodcastArtworkPreparation
from iPodDB.library import ArtworkPixels, TimedArtworkFrame


class Loader:
    def __init__(self) -> None:
        self.requests: list[PodcastArtworkRequest] = []

    def load_artwork(self, request: PodcastArtworkRequest) -> PodcastArtworkImage:
        self.requests.append(request)
        if request.source_url.endswith("bad.jpg"):
            raise OSError("missing publisher picture")
        return PodcastArtworkImage(
            request.source_url, request.source_url, 2, 1, b"\xff\x00\x00" * 2
        )


def test_json_image_times_exclude_invalid_values_and_keep_silent_markers() -> None:
    payload = json.dumps(
        {
            "version": "1.2.0",
            "chapters": [
                {"startTime": 2.125, "img": "two.jpg", "toc": False},
                {"startTime": 0, "title": "No image"},
                {"startTime": 1, "img": "one.jpg"},
                {"startTime": True, "img": "bad.jpg"},
                {"startTime": -1, "img": "bad.jpg"},
                {"startTime": float("nan"), "img": "bad.jpg"},
                {"startTime": float("inf"), "img": "bad.jpg"},
                {"startTime": 1e100, "img": "bad.jpg"},
                {"startTime": 1, "img": "file:///C:/bad.jpg"},
                {"startTime": 1, "img": "https://[broken"},
            ],
        }
    ).encode()
    assert parse_chapter_images(payload, "https://publisher.test/chapters.json") == (
        PodcastChapterImage(1000, "https://publisher.test/one.jpg"),
        PodcastChapterImage(2125, "https://publisher.test/two.jpg"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"no json",
        b"[]",
        b'{"version":"2.0","chapters":[]}',
        json.dumps({"version": "1.2", "chapters": [{}] * 4097}).encode(),
        json.dumps(
            {
                "version": "1.2",
                "chapters": [{"startTime": n, "img": "image.jpg"} for n in range(129)],
            }
        ).encode(),
    ],
)
def test_invalid_or_excessive_chapter_documents_fail_bounded(payload: bytes) -> None:
    with pytest.raises(PodcastFeedError):
        parse_chapter_images(payload, "https://publisher.test/")


def test_cover_fallback_and_shared_images_use_one_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_artwork, "MAX_PODCAST_COVER_BYTES", 12)
    loader = Loader()
    batch = PodcastArtworkPreparation(
        checkpoint=lambda: None,
        progress=lambda _: None,
        loader=loader,
        retained_bytes=6,
    )
    show = PodcastSubscription(
        "show",
        "",
        "Show",
        SubscriptionSource.USER,
        artwork_url="https://publisher.test/show.jpg",
    )
    episode = PodcastEpisode("one", artwork_url="https://publisher.test/bad.jpg")
    first = batch.cover(show, episode, 128)
    assert first is not None
    assert batch.cover(show, replace(episode, episode_id="two"), 128) is first
    assert len(loader.requests) == 2
    assert batch.remaining_bytes == 0
    assert (
        batch.cover(
            show, replace(episode, artwork_url="https://publisher.test/extra.jpg"), 128
        )
        is first
    )
    assert len(batch.issues) == 2


def test_remote_pictures_fill_times_without_replacing_embedded_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def fetch(url: str, **_kwargs: object) -> tuple[bytes, str]:
        requested.append(url)
        return (
            b'{"version":"1.2","chapters":[{"startTime":0.1,"img":"remote.jpg"},{"startTime":0.15,"img":"later.jpg","toc":false}]}',
            "https://cdn.test/images.json",
        )

    monkeypatch.setattr(chapter_artwork, "request_podcast_bytes", fetch)
    loader = Loader()
    batch = PodcastArtworkPreparation(
        checkpoint=lambda: None, progress=lambda _: None, loader=loader
    )
    embedded = TimedArtworkFrame(100, ArtworkPixels(1, 1, b"\x00\xff\x00"))
    episode = PodcastEpisode(
        "one",
        chapter_document_url="https://publisher.test/chapters.json",
        chapter_images=(
            PodcastChapterImage(50, "https://publisher.test/inline.jpg"),
            PodcastChapterImage(300, "https://publisher.test/outside.jpg"),
        ),
    )
    frames = batch.chapter_images(episode, 250, 128, (embedded,))
    assert [f.display_time_ms for f in frames] == [50, 100, 150]
    assert frames[1] is embedded
    assert [r.source_url for r in loader.requests] == [
        "https://publisher.test/inline.jpg",
        "https://cdn.test/later.jpg",
    ]
    assert all(r.preserve_aspect for r in loader.requests)
    assert len(batch.issues) == 1
    assert requested == [episode.chapter_document_url]


@pytest.mark.parametrize("cancel", (False, True))
def test_failed_document_preserves_inline_pictures_but_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    def fail(_url: str, **_kwargs: object) -> tuple[bytes, str]:
        if cancel:
            raise PreparationCancelledError
        raise OSError("unavailable chapter document")

    monkeypatch.setattr(chapter_artwork, "request_podcast_bytes", fail)
    batch = PodcastArtworkPreparation(
        checkpoint=lambda: None, progress=lambda _: None, loader=Loader()
    )
    episode = PodcastEpisode(
        "one",
        chapter_document_url="https://publisher.test/chapters.json",
        chapter_images=(PodcastChapterImage(0, "https://publisher.test/inline.jpg"),),
    )
    if cancel:
        with pytest.raises(PreparationCancelledError):
            batch.chapter_images(episode, 250, 128, ())
    else:
        assert len(batch.chapter_images(episode, 250, 128, ())) == 1
        assert len(batch.issues) == 1
