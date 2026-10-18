"""Finder captures retain embedded covers even when native artwork is absent."""

from __future__ import annotations

import base64
import io
import shutil
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, Any

import mutagen.id3 as frames
import pytest
from PIL import Image
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpener,
    PodcastOpenerFactory,
    PodcastResponse,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.media.sync_artwork import capture_embedded_chapter_artwork
from iOpenPod.app.media.transcoding import LossyEncoder, TranscodeSettings
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.podcasts import feed_client, media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import ArtworkPixels, MediaKind, TrackChapter
from storage import HostPath

if TYPE_CHECKING:
    from pathlib import Path
    from urllib.request import Request

_FRAMES: Any = frames


def _image(color: str, size: tuple[int, int] = (64, 32)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    "condition", ("duplicate", "corrupt", "budget", "off_timeline")
)
def test_chapter_image_capture_bounds_failures_and_duplicate_times(
    tmp_path: Path, condition: str
) -> None:
    source = tmp_path / "chapters.mp3"
    tags = _FRAMES.ID3()
    for identity, data in (
        ("a", b"invalid" if condition == "corrupt" else _image("blue")),
        ("b", _image("red")),
    ):
        tags.add(
            _FRAMES.CHAP(
                element_id=identity,
                start_time=100,
                end_time=200,
                sub_frames=[_FRAMES.APIC(mime="image/png", type=3, data=data)],
            )
        )
    tags.save(source)
    result = capture_embedded_chapter_artwork(
        HostPath(source),
        128,
        frozenset((200 if condition == "off_timeline" else 100,)),
        max_bytes=1 if condition == "budget" else 64_000,
        checkpoint=lambda: None,
    )
    assert len(result.frames) == (0 if condition in ("budget", "off_timeline") else 1)
    if condition == "duplicate":
        assert isinstance(result.frames[0].source, ArtworkPixels)
        assert result.frames[0].source.rgb888[:3] == bytes((0, 0, 255))
    if condition == "corrupt":
        assert isinstance(result.frames[0].source, ArtworkPixels)
        assert result.frames[0].source.rgb888[:3] == bytes((255, 0, 0))
    assert bool(result.skipped) == (condition in ("corrupt", "budget"))


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("embedded_kind", ("valid", "corrupt", "oversized"))
@pytest.mark.parametrize("reencode", (True, False))
def test_episode_cover_precedes_show_cover_and_chapters_reach_native_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    embedded_kind: str,
    reencode: bool,
) -> None:
    # Generated media models the captured APIC + CHAP shape without shipping
    # downloaded Episodes, artwork, account identifiers, or publisher text.
    source = tmp_path / "episode.mp3"
    source.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    tags = _FRAMES.ID3(source)
    embedded_valid = embedded_kind == "valid"
    payload = (
        _image("blue")
        if embedded_valid
        else _image("blue", (8193, 1))
        if embedded_kind == "oversized"
        else b"bad"
    )
    tags.add(_FRAMES.APIC(mime="image/png", type=3, data=payload))
    tags.add(
        _FRAMES.CHAP(
            element_id="intro",
            start_time=0,
            end_time=100,
            sub_frames=[_FRAMES.TIT2(text=["Introduction"])],
        )
    )
    tags.add(
        _FRAMES.CHAP(
            element_id="topic",
            start_time=100,
            end_time=240,
            sub_frames=[
                _FRAMES.TIT2(text=["Topic"]),
                _FRAMES.APIC(mime="image/png", type=3, data=_image("lime")),
            ],
        )
    )
    tags.save(source, v2_version=3)
    monkeypatch.setattr(
        media, "build_opener", PodcastOpenerFactory(source.read_bytes())
    )
    publisher = PodcastOpener(_image("red"))
    requested_covers: list[str] = []

    def load_publisher(request: Request, *, timeout: int) -> PodcastResponse:
        requested_covers.append(request.full_url)
        return publisher.open(request, timeout=timeout)

    monkeypatch.setattr(feed_client, "urlopen", load_publisher)
    addition = podcast_addition()
    addition = replace(
        addition,
        subscription=replace(
            addition.subscription, artwork_url="https://publisher.example/show.png"
        ),
    )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    device = build_device(tmp_path)
    try:
        request = replace(
            podcast_request(device.active),
            settings=TranscodeSettings(
                retranscode_lossy=reencode,
                smart_spoken_word=False,
                lossy_encoder=LossyEncoder.MP3,
            ),
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        saved = device.coordinator.select_device(device.active.candidate.id)
        podcast = next(
            t for t in saved.library.tracks if t.media_kind is MediaKind.PODCAST
        )
        assert podcast.metadata.chapters == (
            TrackChapter("Introduction", 0),
            TrackChapter("Topic", 100),
        )
        assert podcast.artwork_id > 0
        timed = device.coordinator.load_artwork(
            ArtworkRequest(podcast.artwork_id, 128, display_time_ms=100)
        )
        assert timed is not None
        center = ((timed.height // 2) * timed.width + timed.width // 2) * 3
        assert timed.rgb888[center + 1] >= 240
        assert podcast.metadata.artwork_count == 2
        decoded = device.coordinator.load_artwork(
            ArtworkRequest(podcast.artwork_id, 128)
        )
        assert decoded is not None
        center = ((decoded.height // 2) * decoded.width + decoded.width // 2) * 3
        red, green, blue = decoded.rgb888[center : center + 3]
        if embedded_valid:
            assert blue >= 240 and red <= 12 and green <= 12
        else:
            assert red >= 240 and blue <= 12 and green <= 12
        assert requested_covers == (
            [] if embedded_valid else ["https://publisher.example/show.png"]
        )
        if embedded_kind == "oversized":
            assert any(
                issue.code == "sync.podcast_embedded_artwork_skipped"
                for issue in result.issues
            )
    finally:
        device.coordinator.close()
