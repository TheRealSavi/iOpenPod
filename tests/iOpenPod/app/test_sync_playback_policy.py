"""Sync repairs required playback options without replacing retained media."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.podcasts.podcast_test_support import active_ipod
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    _draft,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.sync_plan import SyncPlan
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import LibrarySnapshot, MediaType, Track
from storage.media_processing import MediaTools


def _request(active: ActiveIPod) -> SyncExecutionRequest:
    return SyncExecutionRequest(
        SyncPlan(()),
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        active,
        1,
        1,
        reconcile_playlists=False,
    )


@pytest.mark.parametrize(
    "kind",
    (
        MediaType.PODCAST,
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.VIDEO_PODCAST,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
    ),
)
def test_sync_draft_repairs_retained_playback_flags(kind: MediaType) -> None:
    track = Track(1, "Retained episode", "", "", 1_000, media_types=(kind,))
    music = Track(2, "Music", "", "", 1_000, media_types=(MediaType.AUDIO,))
    active = replace(active_ipod(), library=LibrarySnapshot(tracks=(track, music)))

    draft, _, _ = _draft(_request(active), [], [])

    repaired, retained_music = draft.snapshot.tracks
    assert repaired.metadata.remember_position
    assert repaired.metadata.skip_shuffle
    assert retained_music == music
    assert not draft.media and not draft.replace_media
    assert not track.metadata.remember_position
    assert not track.metadata.skip_shuffle


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        pytest.fail("Playback option repair must not require media tools")


@pytest.mark.parametrize("kind", (MediaType.PODCAST, MediaType.VIDEO_PODCAST))
@pytest.mark.parametrize("playback_enabled", (False, True))
def test_sync_saves_playback_repairs_without_media_changes(
    tmp_path: Path, kind: MediaType, playback_enabled: bool
) -> None:
    device = build_device(tmp_path)
    try:
        first, music = device.active.library.tracks
        incorrect = replace(
            first,
            media_types=(kind,),
            play_count=7,
            metadata=replace(
                first.metadata,
                remember_position=playback_enabled,
                skip_shuffle=playback_enabled,
                podcast=False,
                bookmark_time_ms=450,
                last_played=1_700_000_000,
            ),
        )
        # Model an existing Library written by an older application. The raw
        # coordinator must preserve requested metadata independently of app policy.
        seeded = device.save(
            device.prepare(replace(device.active.library, tracks=(incorrect, music)))
        )
        assert seeded.active is not None, seeded.issues
        device.coordinator.finalize_sync_success(seeded.active, seeded.recovery_path)
        before = device.active
        assert before.library.tracks[0].metadata.remember_position is playback_enabled
        assert before.library.tracks[0].metadata.skip_shuffle is playback_enabled
        assert not before.library.tracks[0].metadata.podcast
        media = {
            track.metadata.location: (
                device.root / track.metadata.location
            ).read_bytes()
            for track in before.library.tracks
        }

        result = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(_request(before), lambda _: None, Event())

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        repaired, retained_music = result.active.library.tracks
        assert repaired.track_id == first.track_id
        assert repaired.metadata.remember_position
        assert repaired.metadata.skip_shuffle
        assert repaired.metadata.podcast
        assert repaired.play_count == 7
        assert repaired.metadata.bookmark_time_ms == 450
        assert repaired.metadata.last_played == 1_700_000_000
        assert retained_music == music
        assert all(
            (device.root / path).read_bytes() == content
            for path, content in media.items()
        )
        reloaded = device.coordinator.select_device(before.candidate.id)
        assert reloaded.library.tracks[0].metadata.remember_position
        assert reloaded.library.tracks[0].metadata.skip_shuffle
        assert reloaded.library.tracks[0].metadata.podcast

        headers = {
            selection.chunk.header.track_id: selection.chunk.header
            for selection in parse_iTunesDB(
                (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
            ).find_chunks(MhitHeader)
        }
        assert headers[first.track_id].podcast_now_playing_flag == 1
        assert headers[music.track_id].podcast_now_playing_flag == 0

        # With repaired flags, another Sync has no database work to publish.
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        original_bytes = database.read_bytes()
        repeated = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(_request(reloaded), lambda _: None, Event())
        assert repeated.status is SyncExecutionStatus.SUCCESS, repeated.issues
        assert not repeated.completed
        assert database.read_bytes() == original_bytes
    finally:
        device.coordinator.close()
