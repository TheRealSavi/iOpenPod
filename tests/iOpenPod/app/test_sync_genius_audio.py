"""Acoustic profiles flow through real Sync preparation and publication."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_genius import (
    _refresh_request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.genius_analysis import GeniusAnalysisService, GeniusAudioDecodeError
from iOpenPod.app.genius_audio import GeniusAudioProfile
from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library.genius import (
    GeniusConfig,
    GeniusMetadata,
    GeniusSpacingRule,
    parse_genius_database,
)
from storage import AtomicHostFile, DevicePath, FilesystemSession, HostPath


class _Decoder:
    def __init__(self, action: Callable[[], None] | None = None) -> None:
        self.calls: list[HostPath | DevicePath] = []
        self.action = action

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        checkpoint()
        assert input_suffix and session.is_active
        self.calls.append(source)
        if self.action is not None:
            self.action()
        checkpoint()
        return b"test audio"


def _profile(
    pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
) -> GeniusAudioProfile:
    assert pcm == b"test audio" and sample_rate_hz == 22_050
    checkpoint()
    return GeniusAudioProfile(30.0, None, (1.0,) * 29, None)


def _with_analysis(device: Device, cache: Path, decoder: _Decoder) -> Device:
    device.coordinator.close()
    coordinator = DeviceCoordinator(
        device.storage,
        genius_analysis=GeniusAnalysisService(
            AtomicHostFile(cache), decoder, profiler=_profile
        ),
    )
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    return replace(device, coordinator=coordinator)


@pytest.mark.parametrize("model", ["MB565", "MD479"])
def test_sync_profiles_retained_audio_and_reuses_persistent_cache(
    tmp_path: Path, model: str
) -> None:
    cache = tmp_path / "profiles.json"
    decoder = _Decoder()
    device = _with_analysis(
        build_device(tmp_path, model=model, compressed_database=model == "MD479"),
        cache,
        decoder,
    )
    try:
        progress: list[WriteProgress] = []
        result = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), progress.append, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert not any(issue.code.startswith("genius.") for issue in result.issues)
        assert len(decoder.calls) == 2
        assert all(isinstance(source, DevicePath) for source in decoder.calls)
        active = [
            event.active_items
            for event in progress
            if event.phase == "draft.genius.audio" and event.active_items
        ]
        assert active and len(active[0]) == 2
        assert {item.item_id for item in active[0]} == {
            f"genius:{track.track_id}" for track in device.active.library.tracks
        }
        path = device.root / (
            "iPod_Control/iTunes/iTunes Library.itlp/Genius.itdb"
            if model == "MD479"
            else "iPod_Control/iTunes/Extras.itdb"
        )
        graph = parse_genius_database(path.read_bytes()).data
        config = graph.configs[0].payload
        assert isinstance(config, GeniusConfig)
        assert config.entries == (
            GeniusSpacingRule(1, 1, 6, 2),
            GeniusSpacingRule(2, 1, 10, 2),
        )
        assert all(isinstance(row.payload, GeniusMetadata) for row in graph.metadata)
        # A new coordinator/service proves reuse is persistent, not just a live map.
        device = _with_analysis(device, cache, decoder)
        second = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), lambda _: None, Event()
        )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert len(decoder.calls) == 2
        assert parse_genius_database(path.read_bytes()).data == graph
    finally:
        device.coordinator.close()


def test_sync_analyzes_prepared_new_media_on_host(tmp_path: Path) -> None:
    decoder = _Decoder()
    device = _with_analysis(build_device(tmp_path), tmp_path / "profiles.json", decoder)
    try:
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, _host(tmp_path, "New song")), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert len(decoder.calls) == 3
        assert sum(isinstance(source, HostPath) for source in decoder.calls) == 1
        assert not any(issue.code.startswith("genius.") for issue in result.issues)
    finally:
        device.coordinator.close()


def test_sync_warning_identifies_unreadable_track_and_device_path(
    tmp_path: Path,
) -> None:
    def unreadable() -> None:
        raise GeniusAudioDecodeError("Invalid audio container")

    device = _with_analysis(
        build_device(tmp_path), tmp_path / "profiles.json", _Decoder(unreadable)
    )
    try:
        track = device.active.library.tracks[0]
        result = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        warning = next(
            issue for issue in result.issues if issue.code == "genius.analysis_warning"
        )
        assert track.title in warning.detail
        assert track.metadata.location in warning.detail
        assert "Invalid audio container" in warning.detail
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("when", ["before_save", "prepared"])
def test_changed_analyzed_audio_blocks_genius_publication(
    tmp_path: Path, when: str
) -> None:
    device = _with_analysis(
        build_device(tmp_path), tmp_path / "profiles.json", _Decoder()
    )
    try:
        active = device.active
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library, active, 1, 1, regenerate_genius=True
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        media_path = device.root / active.library.tracks[0].metadata.location

        def change() -> None:
            media_path.write_bytes(b"changed after acoustic analysis")

        def progress(value: WriteProgress) -> None:
            if when == "prepared" and value.phase == "save.storage.prepared":
                change()

        if when == "before_save":
            change()
        result = device.coordinator.save_library(review, active, progress, Event())
        assert result.active is None
        assert result.issues
        assert not (device.root / "iPod_Control/iTunes/Extras.itdb").exists()
        database = "iPod_Control/iTunes/iTunesDB"
        assert (device.root / database).read_bytes() == device.original[database]
    finally:
        device.coordinator.close()


def test_cancel_during_acoustic_decode_leaves_device_unchanged(tmp_path: Path) -> None:
    cancelled = Event()
    device = _with_analysis(
        build_device(tmp_path),
        tmp_path / "profiles.json",
        _Decoder(action=cancelled.set),
    )
    try:
        result = SyncExecutor(device.coordinator).execute(
            _refresh_request(device.active), lambda _: None, cancelled
        )
        assert result.status is SyncExecutionStatus.CANCELLED, result.issues
        device.assert_original()
    finally:
        device.coordinator.close()
