"""Publisher images reach native artwork without importing chapter navigation."""

from __future__ import annotations

import base64
import io
import shutil
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, Any

import mutagen.id3 as id3
import pytest
from PIL import Image
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.media.transcoding import LossyEncoder, TranscodeSettings
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.podcasts import chapter_artwork, feed_client, media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import MediaKind, TrackChapter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_ID3: Any = id3


def image_bytes(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 32), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for Podcast preparation",
)
@pytest.mark.parametrize("model", ("MB565", "MD480"), ids=("classic", "nano7"))
@pytest.mark.parametrize("episode_cover_valid", (True, False))
def test_publisher_episode_cover_and_timed_images_survive_native_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    episode_cover_valid: bool,
) -> None:
    source = tmp_path / "episode.mp3"
    source.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    tags = _ID3.ID3(source)
    tags.add(
        _ID3.CHAP(
            element_id="intro",
            start_time=0,
            end_time=100,
            sub_frames=[_ID3.TIT2(text=["Embedded intro"])],
        )
    )
    tags.add(
        _ID3.CHAP(
            element_id="topic",
            start_time=100,
            end_time=240,
            sub_frames=[
                _ID3.TIT2(text=["Embedded topic"]),
                _ID3.APIC(mime="image/png", type=3, data=image_bytes("lime")),
            ],
        )
    )
    tags.save(source, v2_version=3)
    monkeypatch.setattr(
        media, "build_opener", PodcastOpenerFactory(source.read_bytes())
    )
    requested: list[str] = []

    def fetch(
        url: str, *, checkpoint: Callable[[], None] | None = None, **_kwargs: object
    ) -> tuple[bytes, str]:
        if checkpoint is not None:
            checkpoint()
        requested.append(url)
        if url.endswith("chapters.json"):
            return (
                b'{"version":"1.2.0","chapters":[{"startTime":0.05,"img":"yellow.png","toc":false},{"startTime":0.1,"img":"do-not-fetch.png"},{"startTime":0.15,"img":"red.png","title":"Not a new chapter"}]}',
                url,
            )
        if url.endswith("episode.png") and not episode_cover_valid:
            raise OSError("episode image unavailable")
        colors = {
            "episode.png": "blue",
            "show.png": "red",
            "yellow.png": "yellow",
            "red.png": "red",
        }
        return image_bytes(colors[url.rsplit("/", 1)[-1]]), url

    monkeypatch.setattr(feed_client, "request_podcast_bytes", fetch)
    monkeypatch.setattr(chapter_artwork, "request_podcast_bytes", fetch)
    addition = podcast_addition()
    addition = replace(
        addition,
        subscription=replace(
            addition.subscription,
            artwork_url="https://publisher.test/show.png",
            copyright="Publisher copyright",
        ),
        episode=replace(
            addition.episode,
            author="Episode author",
            artwork_url="https://publisher.test/episode.png",
            chapter_document_url="https://publisher.test/chapters.json",
        ),
    )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    device = build_device(tmp_path, model=model, compressed_database=model == "MD480")
    try:
        request = replace(
            podcast_request(device.active),
            settings=TranscodeSettings(
                retranscode_lossy=True,
                smart_spoken_word=False,
                lossy_encoder=LossyEncoder.MP3,
            ),
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        saved = device.coordinator.select_device(device.active.candidate.id)
        track = next(
            t for t in saved.library.tracks if t.media_kind is MediaKind.PODCAST
        )
        assert track.artist == "Episode author"
        assert track.album_artist == addition.subscription.author
        assert track.metadata.copyright == "Publisher copyright"
        assert track.metadata.chapters == (
            TrackChapter("Embedded intro", 0),
            TrackChapter("Embedded topic", 100),
        )
        assert track.metadata.artwork_count == 4
        for position, expected in (
            (0, (0, 0, 255) if episode_cover_valid else (255, 0, 0)),
            (50, (255, 255, 0)),
            (100, (0, 255, 0)),
            (150, (255, 0, 0)),
        ):
            image = device.coordinator.load_artwork(
                ArtworkRequest(track.artwork_id, 128, display_time_ms=position)
            )
            assert image is not None
            center = ((image.height // 2) * image.width + image.width // 2) * 3
            assert all(
                abs(a - b) <= 16
                for a, b in zip(
                    image.rgb888[center : center + 3], expected, strict=True
                )
            )
        assert "https://publisher.test/do-not-fetch.png" not in requested
        assert (
            "https://publisher.test/show.png" in requested
        ) is not episode_cover_valid
    finally:
        device.coordinator.close()
