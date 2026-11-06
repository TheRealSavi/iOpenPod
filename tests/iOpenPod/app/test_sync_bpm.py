"""BPM and Genius share one cached analysis and ordinary publication paths."""

import base64
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Protocol, cast

import pytest
from mutagen.mp4 import MP4
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_smart_playlist_refresh import (
    _saved_memberships,  # pyright: ignore[reportPrivateUsage]
    _seed,  # pyright: ignore[reportPrivateUsage]
    _smart,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_genius import (
    _refresh_request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_genius_audio import (
    _Decoder,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_updates import (
    _NoMediaPreparation,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.genius_analysis import GeniusAnalysisService, GeniusAudioDecodeError
from iOpenPod.app.genius_audio import GeniusAudioProfile
from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.sync_bpm import with_missing_bpm
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor, SyncOptions
from iOpenPod.app.sync_plan import SyncPlanAction, prepare_sync_plan
from iOpenPod.app.sync_track_details import track_tag_sha256
from iPodDB.library import (
    LibrarySnapshot,
    MediaType,
    SmartField,
    SmartOperator,
    SmartRule,
    Track,
    TrackMetadata,
)
from storage import AtomicHostFile, HostPath


def _with_analysis(
    device: Device, cache: Path, decoder: _Decoder, tempo: float = 124.4
) -> Device:
    def profile(
        pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
    ) -> GeniusAudioProfile:
        checkpoint()
        return GeniusAudioProfile(30.0, None, (tempo, *(1.0 for _ in range(28))), None)

    device.coordinator.close()
    coordinator = DeviceCoordinator(
        device.storage,
        genius_analysis=GeniusAnalysisService(
            AtomicHostFile(cache), decoder, profiler=profile
        ),
    )
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    return replace(device, coordinator=coordinator)


class _Tags(Protocol):
    def __getitem__(self, key: str) -> object: ...


_read_tags = cast("Callable[[Path], _Tags]", MP4)


@pytest.mark.parametrize("model", ["MB565", "MD479", "MA002"])
@pytest.mark.parametrize(
    "bpm,genius", [(False, False), (True, False), (False, True), (True, True)]
)
def test_one_shared_pass_with_independent_settings(
    tmp_path: Path, model: str, bpm: bool, genius: bool
) -> None:
    decoder = _Decoder()
    device = _with_analysis(
        build_device(tmp_path, model=model, compressed_database=model == "MD479"),
        tmp_path / "profiles.json",
        decoder,
    )
    try:
        host = _host(tmp_path, "New song")
        request = replace(
            _request(device, host),
            options=SyncOptions(compute_missing_bpm=bpm, analyze_for_genius=genius),
        )
        progress: list[WriteProgress] = []
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress.append, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert all(
            t.metadata.bpm == (124 if bpm else 0) for t in result.active.library.tracks
        )
        native_genius = genius and model != "MA002"
        assert len(decoder.calls) == (3 if bpm or native_genius else 0)
        assert sum(isinstance(p, HostPath) for p in decoder.calls) == int(
            bpm or native_genius
        )
        assert any(p.phase == "draft.genius.rank" for p in progress) == native_genius
        assert not any(p.phase == "sync.bpm" for p in progress)
        assert (
            Path(host.sources[0].path.path).read_bytes()
            == b"Prepared media for New song"
        )
    finally:
        device.coordinator.close()


def test_bpm_reuses_profiles_from_an_earlier_genius_sync(tmp_path: Path) -> None:
    decoder = _Decoder()
    cache = tmp_path / "profiles.json"
    device = _with_analysis(build_device(tmp_path), cache, decoder)
    try:
        first = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), lambda _: None, Event()
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert len(decoder.calls) == 2
        device = _with_analysis(device, cache, decoder)
        second = SyncExecutor(device.coordinator).execute(
            replace(
                _refresh_request(device.active),
                options=SyncOptions(compute_missing_bpm=True, analyze_for_genius=False),
            ),
            lambda _: None,
            Event(),
        )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None
        assert all(t.metadata.bpm == 124 for t in second.active.library.tracks)
        assert len(decoder.calls) == 2
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.parametrize("initially_enabled", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_tags_history_and_cache_for_new_and_retained_tracks(
    tmp_path: Path, rockbox: bool, initially_enabled: bool, refresh: bool
) -> None:
    payload = base64.b64decode(
        (Path(__file__).parents[2] / "fixtures/media/tone.m4a.b64").read_bytes()
    )
    decoder = _Decoder()
    cache = tmp_path / "profiles.json"
    device = _with_analysis(
        build_device(tmp_path, media_payload=payload), cache, decoder
    )
    try:
        host = _host(tmp_path, "Song", payload=payload)
        request = replace(
            _request(device, host),
            options=SyncOptions(
                compute_missing_bpm=initially_enabled,
                analyze_for_genius=False,
                rockbox_metadata=rockbox,
            ),
        )
        first = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None and first.helper is not None
        original = next(t for t in first.active.library.tracks if t.title == "Song")
        original_media = (device.root / original.metadata.location).read_bytes()
        comparison = prepare_sync_plan(host, first.helper, first.active.library)
        selected = replace(
            comparison, items=tuple(i for i in comparison.items if i.host_path)
        )
        assert selected.items[0].action is SyncPlanAction.UNCHANGED
        repeat = (
            _refresh_request(first.active)
            if refresh
            else replace(request, plan=selected, source=first.active, ipod=first.helper)
        )
        result = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(
            replace(repeat, options=replace(request.options, compute_missing_bpm=True)),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        track = next(t for t in result.active.library.tracks if t.title == "Song")
        assert track.metadata.bpm == 124 and track.track_id == original.track_id
        path = device.root / track.metadata.location
        assert path.stat().st_size == track.size_bytes
        if rockbox:
            assert _read_tags(path)["tmpo"] == [124]
        else:
            assert path.read_bytes() == original_media
        assert Path(host.sources[0].path.path).read_bytes() == payload
        assert len(decoder.calls) == 3
        helper = result.helper or first.helper
        repeated = prepare_sync_plan(host, helper, result.active.library)
        assert (
            next(i for i in repeated.items if i.host_path).action
            is SyncPlanAction.UNCHANGED
        )
        # New cache instance must reuse profiles even after tag-only byte changes.
        device = _with_analysis(device, cache, decoder)
        third = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), lambda _: None, Event()
        )
        assert third.status is SyncExecutionStatus.SUCCESS, third.issues
        assert len(decoder.calls) == 3
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "outcome", ["failure", "cancel", "skip", "skip_active", "silence", "changed"]
)
def test_shared_analysis_failure_skip_and_cancellation(
    tmp_path: Path, outcome: str
) -> None:
    cancelled = Event()

    def action() -> None:
        if outcome == "skip_active":
            request.genius_analysis_skip.set()
        if outcome == "failure":
            raise GeniusAudioDecodeError("Undecodable music")
        if outcome == "cancel":
            cancelled.set()
        if outcome == "changed":
            (
                device.root / device.active.library.tracks[0].metadata.location
            ).write_bytes(b"changed source")

    decoder = _Decoder(action)
    device = _with_analysis(
        build_device(tmp_path),
        tmp_path / "profiles.json",
        decoder,
        tempo=0 if outcome == "silence" else 124,
    )
    try:
        host = _host(tmp_path, "Song")
        request = replace(
            _request(device, host),
            options=SyncOptions(compute_missing_bpm=True, analyze_for_genius=False),
        )

        def progress(value: WriteProgress) -> None:
            if outcome == "skip" and value.phase == "draft.genius":
                request.genius_analysis_skip.set()

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, cancelled
        )
        if outcome in ("cancel", "changed"):
            assert result.status is (
                SyncExecutionStatus.CANCELLED
                if outcome == "cancel"
                else SyncExecutionStatus.FAILED
            ), result.issues
            assert not any(t.title == "Song" for t in device.active.library.tracks)
        else:
            assert result.status is SyncExecutionStatus.SUCCESS, result.issues
            assert result.active is not None
            assert all(t.metadata.bpm == 0 for t in result.active.library.tracks)
        if outcome == "skip":
            assert not decoder.calls
        if outcome == "failure":
            assert any(i.code == "genius.analysis_warning" for i in result.issues)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "tempo,expected",
    [
        (124.4, 124),
        (124.5, 125),
        (0.0, 0),
        (float("nan"), 0),
        (float("inf"), 0),
        (65536.0, 0),
    ],
)
def test_tempo_populates_only_missing_music_bpm(tempo: float, expected: int) -> None:
    music = Track(1, "Music", "Artist", "Album", 1000, metadata=TrackMetadata(bpm=0))
    tagged = replace(music, track_id=2, metadata=replace(music.metadata, bpm=87))
    previous = replace(music, track_id=3, metadata=replace(music.metadata, bpm=90))
    non_music = tuple(
        replace(music, track_id=4 + i, media_types=(kind,))
        for i, kind in enumerate(
            (
                MediaType.PODCAST,
                MediaType.AUDIOBOOK,
                MediaType.MUSIC_VIDEO,
                MediaType.VIDEO,
            )
        )
    )
    tracks = (
        music,
        tagged,
        replace(previous, metadata=replace(previous.metadata, bpm=0)),
        *non_music,
    )
    profile = GeniusAudioProfile(30.0, None, (tempo, *(1.0 for _ in range(28))), None)
    result = with_missing_bpm(
        LibrarySnapshot(tracks=tracks),
        LibrarySnapshot(tracks=(previous,)),
        {t.track_id: profile for t in tracks},
    )
    assert [t.metadata.bpm for t in result.tracks] == [expected, 87, 90, 0, 0, 0, 0]


@pytest.mark.parametrize("add_track", [False, True])
def test_smart_playlists_see_calculated_bpm_in_the_same_sync(
    tmp_path: Path, add_track: bool
) -> None:
    decoder = _Decoder()
    device = _with_analysis(build_device(tmp_path), tmp_path / "profiles.json", decoder)
    try:
        _seed(
            device,
            (_smart(10, SmartRule(SmartField.BPM, SmartOperator.GREATER_THAN, 120)),),
        )
        host = _host(tmp_path, *(("New song",) if add_track else ()))
        request = replace(
            _request(device, host),
            reconcile_playlists=False,
            options=SyncOptions(compute_missing_bpm=True, analyze_for_genius=False),
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert set(_saved_memberships(device)["Smart 10"]) == {
            t.track_id for t in result.active.library.tracks
        }
    finally:
        device.coordinator.close()


def test_calculated_bpm_does_not_hide_an_unrelated_device_edit(tmp_path: Path) -> None:
    device = _with_analysis(
        build_device(tmp_path), tmp_path / "profiles.json", _Decoder()
    )
    try:
        host = _host(tmp_path, "Song")
        first = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            replace(
                _request(device, host), options=SyncOptions(analyze_for_genius=False)
            ),
            lambda _: None,
            Event(),
        )
        assert first.active is not None and first.helper is not None
        original = next(t for t in first.active.library.tracks if t.title == "Song")
        dirty = replace(original, title="Edited on device")
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(
                    first.active.library,
                    tracks=tuple(
                        dirty if t.track_id == original.track_id else t
                        for t in first.active.library.tracks
                    ),
                ),
                first.active,
                1,
                1,
            ),
            lambda _: None,
            Event(),
        )
        saved = device.coordinator.save_library(
            review, first.active, lambda _: None, Event()
        )
        assert saved.active is not None, saved.issues
        result = SyncExecutor(device.coordinator).execute(
            replace(
                _refresh_request(saved.active),
                options=SyncOptions(compute_missing_bpm=True, analyze_for_genius=False),
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        changed = next(
            t for t in result.active.library.tracks if t.track_id == original.track_id
        )
        record = next(
            t for t in result.helper.tracks if t.track_id == original.track_id
        )
        assert changed.metadata.bpm == 124 and changed.title == "Edited on device"
        assert record.sync is not None
        assert record.sync.ipod_tag_sha256 == track_tag_sha256(original)
        assert record.sync.ipod_tag_sha256 != track_tag_sha256(changed)
    finally:
        device.coordinator.close()
