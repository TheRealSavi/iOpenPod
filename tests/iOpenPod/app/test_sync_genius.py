"""Sync generates native relationships for the final music Library."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from device_registry import DEFAULT_DEVICE_REGISTRY, FeatureSupport
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    _draft,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.sync_plan import SyncPlan
from iPodDB.genius import GeniusSimilarities
from iPodDB.library import LibrarySnapshot
from iPodDB.library.genius import parse_genius_database
from storage.media_processing import MediaTools


def _refresh_request(active: ActiveIPod) -> SyncExecutionRequest:
    return SyncExecutionRequest(
        SyncPlan(()),
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        active,
        1,
        1,
        reconcile_playlists=False,
    )


class _NoMediaWork(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        pytest.fail("Genius refresh does not require media preparation")


@pytest.mark.parametrize("model", ["MB565", "MD479"])
def test_refresh_library_generates_every_music_track_and_reuses_ids(
    tmp_path: Path, model: str
) -> None:
    sqlite = model == "MD479"
    device = build_device(tmp_path, model=model, compressed_database=sqlite)
    try:
        before = device.active.library
        phases: list[str] = []
        executor = SyncExecutor(device.coordinator, transcoder=_NoMediaWork())
        first = executor.execute(
            _refresh_request(device.active),
            lambda progress: phases.append(progress.phase),
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None
        assignments = {
            t.track_id: t.ipod.genius_id
            for t in first.active.library.tracks
            if t.ipod is not None
        }
        assert len(assignments) == len(before.tracks)
        assert all(assignments.values())
        assert len(set(assignments.values())) == len(assignments)
        assert first.active.library.playlists == before.playlists
        assert first.active.genius.collections == ()
        assert "draft.genius" in phases
        companion = device.root / (
            "iPod_Control/iTunes/iTunes Library.itlp/Genius.itdb"
            if sqlite
            else "iPod_Control/iTunes/Extras.itdb"
        )
        graph = parse_genius_database(companion.read_bytes()).data
        assert {row.genius_id for row in graph.metadata} == set(assignments.values())
        for row in graph.similarities:
            assert isinstance(row.payload, GeniusSimilarities)
            assert set(row.payload.candidates) == set(assignments.values()) - {
                row.genius_id
            }
        second = executor.execute(
            _refresh_request(first.active), lambda _: None, Event()
        )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None
        assert {
            t.track_id: t.ipod.genius_id
            for t in second.active.library.tracks
            if t.ipod is not None
        } == assignments
        assert parse_genius_database(companion.read_bytes()).data == graph
        for track in before.tracks:
            assert (device.root / track.metadata.location).read_bytes() == (
                device.original[track.metadata.location]
            )
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("supported", [False, True])
def test_sync_requests_genius_only_for_confirmed_capability(
    tmp_path: Path, supported: bool
) -> None:
    device = build_device(tmp_path)
    try:
        profile = next(
            profile
            for profile in DEFAULT_DEVICE_REGISTRY.profiles
            if (profile.capabilities.genius.playlists is FeatureSupport.SUPPORTED)
            is supported
        )
        active = replace(device.active, profile=profile)
        draft, _, _ = _draft(_refresh_request(active), [], [])
        assert draft.regenerate_genius is supported
    finally:
        device.coordinator.close()


def test_ordinary_metadata_save_does_not_start_genius(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        before = device.active.library
        desired = replace(
            before,
            tracks=(replace(before.tracks[0], title="Renamed"), *before.tracks[1:]),
        )
        review = device.prepare(desired)
        assert review.result.prepared is not None, review.result.issues
        assert review.plan is not None and review.plan.draft.genius_update is None
        assert review.result.prepared.genius is None
        assert all(
            track.ipod is not None and not track.ipod.genius_id
            for track in review.result.prepared.snapshot.tracks
        )
        assert not (device.root / "iPod_Control/iTunes/Extras.itdb").exists()
    finally:
        device.coordinator.close()


def test_cancel_during_generation_leaves_device_unchanged(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    cancelled = Event()

    def progress(value: WriteProgress) -> None:
        if value.phase == "draft.genius":
            cancelled.set()

    try:
        result = SyncExecutor(device.coordinator, transcoder=_NoMediaWork()).execute(
            _refresh_request(device.active), progress, cancelled
        )
        assert result.status is SyncExecutionStatus.CANCELLED, result.issues
        device.assert_original()
        assert not (device.root / "iPod_Control/iTunes/Extras.itdb").exists()
    finally:
        device.coordinator.close()


def test_new_song_is_included_after_sync_media_preparation(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "New song")
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert len(result.active.library.tracks) == 3
        assert any(t.title == "New song" for t in result.active.library.tracks)
        ids = {
            t.ipod.genius_id for t in result.active.library.tracks if t.ipod is not None
        }
        assert len(ids) == 3 and 0 not in ids
        graph = parse_genius_database(
            (device.root / "iPod_Control/iTunes/Extras.itdb").read_bytes()
        ).data
        assert {row.genius_id for row in graph.similarities} == ids
    finally:
        device.coordinator.close()
