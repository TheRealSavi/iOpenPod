"""Container chapter frame order does not determine Library chapter order."""

from __future__ import annotations

import base64
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

import mutagen.id3 as frames
import pytest
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.importing import MusicImporter
from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.media.transcoding import enrich_source_metadata
from iOpenPod.app.podcasts import media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import MediaKind, Track, TrackChapter, TrackMetadata
from storage import HostPath

_FIRST_TITLE = "A longer first chapter title whose ID3 frame follows the second"
_SECOND_TITLE = "Second"
_FRAMES: Any = frames
_EXPECTED_CHAPTERS = (
    TrackChapter(_FIRST_TITLE, 0),
    TrackChapter(_SECOND_TITLE, 100),
)


@pytest.fixture
def unordered_chapters(tmp_path: Path) -> HostPath:
    if shutil.which("ffprobe") is None:
        pytest.skip("FFprobe is required for chapter inspection")
    path = tmp_path / "chapters.mp3"
    path.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    tags = _FRAMES.ID3(path)
    tags.add(
        _FRAMES.CTOC(
            element_id="toc",
            flags=_FRAMES.CTOCFlags.TOP_LEVEL | _FRAMES.CTOCFlags.ORDERED,
            child_element_ids=["first", "second"],
        )
    )
    tags.add(
        _FRAMES.CHAP(
            element_id="first",
            start_time=0,
            end_time=100,
            sub_frames=[_FRAMES.TIT2(text=[_FIRST_TITLE])],
        )
    )
    tags.add(
        _FRAMES.CHAP(
            element_id="second",
            start_time=100,
            end_time=240,
            sub_frames=[_FRAMES.TIT2(text=[_SECOND_TITLE])],
        )
    )
    # Mutagen writes smaller frames first. The chapter timings and ordered table
    # of contents are valid even when physical CHAP frames are nonchronological.
    tags.save(path, v2_version=3)
    assert [chapter.start_time for chapter in _FRAMES.ID3(path).getall("CHAP")] == [
        100,
        0,
    ]
    return HostPath(path)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is required for real Podcast preparation",
)
def test_podcast_sync_orders_observed_chapters_before_library_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unordered_chapters: HostPath,
) -> None:
    device = build_device(tmp_path)
    monkeypatch.setattr(
        media,
        "build_opener",
        PodcastOpenerFactory(Path(unordered_chapters).read_bytes()),
    )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(podcast_addition(),))),
    )
    try:
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert podcast.metadata.chapters == _EXPECTED_CHAPTERS
    finally:
        device.coordinator.close()


def test_music_import_orders_observed_chapters_before_library_validation(
    tmp_path: Path, unordered_chapters: HostPath
) -> None:
    device = build_device(tmp_path)
    try:
        song = MusicImporter().inspect(
            unordered_chapters, device.active.profile, checkpoint=lambda: None
        )
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        workspace.add_songs((song,), workspace.edit_revision)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                workspace.desired_snapshot(),
                device.active,
                workspace.generation,
                workspace.revision,
                media=workspace.media_sources,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert song.track.metadata.chapters == _EXPECTED_CHAPTERS
    finally:
        device.coordinator.close()


def test_source_enrichment_preserves_explicit_chapters(
    unordered_chapters: HostPath,
) -> None:
    observed = MediaInspector().inspect(unordered_chapters, checkpoint=lambda: None)
    chapters = (TrackChapter("Reviewed second", 150), TrackChapter("Reviewed first", 0))
    reviewed = Track(
        1, "Reviewed", "", "", 250, metadata=TrackMetadata(chapters=chapters)
    )
    assert enrich_source_metadata(reviewed, observed).metadata.chapters == chapters
    # Only an absent chapter collection is populated from the observed media.
    assert (
        enrich_source_metadata(
            replace(reviewed, metadata=TrackMetadata()), observed
        ).metadata.chapters
        == _EXPECTED_CHAPTERS
    )
