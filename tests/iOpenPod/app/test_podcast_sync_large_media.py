"""Podcast metadata rewriting must not impose a whole-media memory budget."""

from __future__ import annotations

import base64
import shutil
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.media.transcoding import LossyEncoder
from iOpenPod.app.podcasts import media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import MediaKind
from storage.media_processing import MediaWorkspace

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from storage import HostPath
    from storage.host_capture import CapturedHostFile


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("rockbox_metadata", (False, True))
@pytest.mark.parametrize("filename", ("tone.mp3", "tone.m4a"))
@pytest.mark.parametrize("transcode", (False, True))
def test_podcast_sync_exceeds_byte_transform_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rockbox_metadata: bool,
    filename: str,
    transcode: bool,
) -> None:
    data = base64.decodebytes((FIXTURES / f"{filename}.b64").read_bytes())
    budget = 64
    byte_transform = MediaWorkspace.transform_bytes

    def small_byte_transform(
        self: MediaWorkspace,
        source: HostPath,
        suffix: str,
        transform: Callable[[bytes], bytes],
        *,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> CapturedHostFile:
        # Exercise the real size guard with a short playable Episode instead of
        # downloading and decoding hours of audio in each regression run.
        return byte_transform(
            self, source, suffix, transform, max_bytes=min(max_bytes, budget)
        )

    monkeypatch.setattr(MediaWorkspace, "transform_bytes", small_byte_transform)
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    addition = podcast_addition()
    addition = replace(
        addition,
        episode=replace(
            addition.episode, enclosure_url=f"https://publisher.example/{filename}"
        ),
    )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    device = build_device(tmp_path)
    request = podcast_request(device.active)
    request = replace(
        request,
        options=replace(request.options, rockbox_metadata=rockbox_metadata),
        settings=replace(
            request.settings,
            smart_spoken_word=transcode,
            lossy_encoder=LossyEncoder.MP3,
        ),
    )
    try:
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert podcast.title == addition.episode.title
        assert podcast.metadata.podcast_guid == addition.episode.guid
        published = device.root / podcast.metadata.location
        assert published.stat().st_size > budget
        if rockbox_metadata:
            if published.suffix == ".mp3":
                tags = ID3(published)  # type: ignore[no-untyped-call]
                assert str(cast("object", tags["TIT2"])) == addition.episode.title
                assert str(cast("object", tags["TPE1"])) == addition.subscription.author
                assert str(cast("object", tags["TALB"])) == addition.subscription.title
            else:
                mp4_tags = MP4(published).tags  # type: ignore[no-untyped-call]
                assert mp4_tags is not None
                assert mp4_tags["\u00a9nam"] == [addition.episode.title]
                assert mp4_tags["\u00a9ART"] == [addition.subscription.author]
                assert mp4_tags["\u00a9alb"] == [addition.subscription.title]
        elif not transcode:
            assert published.read_bytes() == data
    finally:
        device.coordinator.close()
