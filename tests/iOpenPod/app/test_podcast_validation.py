"""An invalid Episode must not block independent Sync work or erase its predecessor."""

from __future__ import annotations

import base64
import shutil
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, Any

import mutagen.id3 as frames
import pytest
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastResponse,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.podcasts import media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import MediaKind

if TYPE_CHECKING:
    from pathlib import Path
    from urllib.request import Request

_FRAMES: Any = frames


class _EpisodeDownloads:
    def __init__(self, invalid: bytes, valid: bytes) -> None:
        self.invalid = invalid
        self.valid = valid

    def __call__(self, *_handlers: object) -> _EpisodeDownloads:
        return self

    def open(self, request: Request, *, timeout: int) -> PodcastResponse:
        assert timeout > 0
        return PodcastResponse(
            self.invalid if request.full_url.endswith("invalid.mp3") else self.valid
        )


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("include_valid", [False, True])
def test_invalid_episode_is_skipped_while_valid_episode_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: bool,
    include_valid: bool,
) -> None:
    path = tmp_path / "invalid.mp3"
    path.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
    tags = _FRAMES.ID3(path)
    tags.add(
        _FRAMES.CHAP(
            element_id="beyond-duration",
            start_time=1000,
            end_time=1100,
            sub_frames=[_FRAMES.TIT2(text=["Invalid chapter"])],
        )
    )
    tags.add(_FRAMES.USLT(encoding=3, lang="eng", desc="", text="Words"))
    tags.save(path, v2_version=3)
    good_media = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(
        media, "build_opener", _EpisodeDownloads(path.read_bytes(), good_media)
    )
    device = build_device(tmp_path)
    try:
        original = device.active.library.tracks[0]
        original_path = device.root / original.metadata.location
        original_bytes = original_path.read_bytes()
        addition = podcast_addition()
        invalid = replace(
            addition,
            episode=replace(
                addition.episode,
                title="Bad Episode",
                enclosure_url="https://publisher.example/invalid.mp3",
            ),
            replaces_track_id=original.track_id if replacement else None,
        )
        valid = replace(
            addition,
            episode=replace(
                addition.episode,
                episode_id="good",
                guid="good-guid",
                title="Good Episode",
                enclosure_url="https://publisher.example/valid.m4a",
            ),
        )
        monkeypatch.setattr(
            "iOpenPod.app.sync_execution.prepare_podcast_sync",
            FixedPodcastPlan(
                PodcastSyncPlan(
                    additions=(invalid, valid) if include_valid else (invalid,)
                )
            ),
        )
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        if include_valid:
            assert result.status is SyncExecutionStatus.PARTIAL, result.issues
            assert result.active is not None
            assert [item.name for item in result.completed] == ["Good Episode"]
            assert [
                track.title
                for track in result.active.library.tracks
                if track.media_kind is MediaKind.PODCAST
            ] == ["Good Episode"]
            assert original in result.active.library.tracks
        else:
            assert result.status is SyncExecutionStatus.FAILED, result.issues
            assert not result.completed
            device.assert_original()
        assert original_path.read_bytes() == original_bytes
        failure = next(i for i in result.issues if i.code == "track.invalid_value")
        assert "Bad Episode" in failure.detail and "Show" in failure.detail
        assert failure.artifact == invalid.episode.enclosure_url
        assert failure.record_id is None  # No invented, shared incoming Track ID.
        assert not any(i.code == "resources.missing_lyrics" for i in result.issues)
        if replacement:
            assert any(
                "awaiting replacement was kept" in i.message for i in result.issues
            )
    finally:
        device.coordinator.close()
