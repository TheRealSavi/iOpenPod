"""Mix ownership and native collections are one recoverable publication."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_classic_genius_mix_publication import classic_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.app.test_nano7_mix_artwork_publication import nano7_device
from tests.iOpenPod.app.test_sync_genius import (
    _refresh_request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import build_context
from whenever import Instant, patch_current_time

from iOpenPod.app import genius_mixes
from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.genius_analysis import GeniusAnalysisService
from iOpenPod.app.genius_mixes import GENIUS_MIX_POLICY, MixPolicy
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
)
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.app.services import genius_mixes as mix_service
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library.genius import parse_genius_database


@pytest.fixture(params=("nano", "classic", "nano7"))
def mix_device(tmp_path: Path, request: pytest.FixtureRequest) -> Device:
    device = (
        nano7_device(tmp_path)
        if request.param == "nano7"
        else classic_device(tmp_path)
        if request.param == "classic"
        else build_device(tmp_path, model="MD479", compressed_database=True)
    )
    request.addfinalizer(device.coordinator.close)
    return device


@pytest.mark.parametrize("delete_track", (False, True))
def test_removing_mix_through_save_controller_does_not_analyze_music(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch, delete_track: bool
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    initial = device.active
    desired = replace(
        initial.library,
        tracks=(
            replace(initial.library.tracks[0], genre="Rock"),
            replace(initial.library.tracks[1], genre="Pop"),
        ),
    )
    created = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            desired,
            initial,
            1,
            1,
            regenerate_genius=True,
            add_genius_mixes=("rock", "pop"),
        ),
        lambda _: None,
        Event(),
    )
    saved = device.save(created)
    assert saved.active is not None, saved.issues
    active = saved.active
    mix = next(c for c in active.genius.collections if c.name == "Rock Mix")
    retained = next(c for c in active.genius.collections if c.name == "Pop Mix")
    graph_path = device.root / "iPod_Control/iTunes/Extras.itdb"
    if not graph_path.exists():
        graph_path = device.root / "iPod_Control/iTunes/iTunes Library.itlp/Genius.itdb"
    graph_before = graph_path.read_bytes()
    analyzed: list[bool] = []

    def unexpected_analysis(
        _service: GeniusAnalysisService, *args: object, **kwargs: object
    ) -> None:
        analyzed.append(True)
        raise AssertionError("Removing a Mix must not analyze music")

    monkeypatch.setattr(GeniusAnalysisService, "analyze", unexpected_analysis)
    context = build_context(device_coordinator=device.coordinator)
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    workspace = context.library_workspace
    workspace.load(active.library)
    controller = context.library_write_controller
    try:
        workspace.remove_genius_collection(mix, workspace.edit_revision)
        if delete_track:
            workspace.remove_tracks(
                (active.library.tracks[0].track_id,), workspace.edit_revision
            )
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert analyzed == [], "Mix removal unexpectedly analyzed music"
        assert (controller.state,) == (PreparationState.READY,)
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        remaining = active.library.tracks[1:] if delete_track else active.library.tracks
        assert device.active.library.tracks == remaining
        assert device.active.genius.collections == (retained,)
        assert device.active.genius_mix_state.entries == tuple(
            e for e in active.genius_mix_state.entries if e.definition_key == "pop"
        )
        if delete_track:
            assert {
                r.genius_id
                for r in parse_genius_database(graph_path.read_bytes()).data.metadata
            } == {t.ipod.genius_id for t in remaining if t.ipod is not None}
        else:
            assert graph_path.read_bytes() == graph_before
    finally:
        context.shutdown()


def test_track_deletion_removes_only_the_emptied_mix_and_its_ownership(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=(
                replace(active.library.tracks[0], genre="Rock"),
                replace(active.library.tracks[1], genre="Pop"),
            ),
        )
        created = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                active,
                1,
                1,
                regenerate_genius=True,
                add_genius_mixes=("rock", "pop"),
            ),
            lambda _: None,
            Event(),
        )
        saved = device.save(created)
        assert saved.active is not None, saved.issues
        active = saved.active
        before = active.genius_mix_state
        assert len(before.entries) == 2
        retained = next(c for c in active.genius.collections if c.name == "Pop Mix")
        state_path = device.root / str(mix_service.MIX_STATE_PATH)
        state_bytes = state_path.read_bytes()
        # The recovery baseline is the Library containing both authored Mixes.
        for relative in device.original:
            device.original[relative] = (device.root / relative).read_bytes()
        workspace = LibraryWorkspace()
        workspace.load(active.library)
        workspace.remove_tracks(
            (active.library.tracks[0].track_id,), workspace.edit_revision
        )
        review = device.prepare(workspace.desired_snapshot(), delete=True)
        assert review.result.prepared is not None, review.result.issues
        assert state_path.read_bytes() == state_bytes
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.genius.collections == (retained,)
        assert saved.active.genius_mix_state.entries == tuple(
            entry for entry in before.entries if entry.definition_key == "pop"
        )
        assert (
            mix_service.decode_mix_state(state_path.read_bytes())
            == saved.active.genius_mix_state
        )
        device.restore(saved.recovery_path)
        assert state_path.read_bytes() == state_bytes
    finally:
        device.coordinator.close()


def test_manual_add_is_staged_and_ownership_rolls_back_with_native_mix(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The common virtual fixture has two Tracks; catalog eligibility is tested
    # separately with the real ten-Track minimum.
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=tuple(replace(t, genre="Rock") for t in active.library.tracks),
        )
        request = LibraryPreparationRequest(
            desired, active, 1, 1, regenerate_genius=True, add_genius_mixes=("rock",)
        )
        review = device.coordinator.prepare_library(request, lambda _: None, Event())
        assert review.result.prepared is not None, review.result.issues
        state_path = device.root / str(mix_service.MIX_STATE_PATH)
        assert not state_path.exists()
        assert str(mix_service.MIX_STATE_PATH) in {
            file.path for file in review.file_changes
        }
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert len(saved.active.genius.collections) == 1
        assert saved.active.genius.collections[0].name == "Rock Mix"
        assert saved.active.genius_mix_state.entries[0].added_at is None
        assert (
            mix_service.decode_mix_state(state_path.read_bytes())
            == saved.active.genius_mix_state
        )
        device.restore(saved.recovery_path)
        assert not state_path.exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("owned", (True, False))
def test_explicit_mix_removal_updates_native_collection_and_ownership(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch, owned: bool
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=tuple(
                replace(track, genre="Rock") for track in active.library.tracks
            ),
        )
        created = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                active,
                1,
                1,
                regenerate_genius=True,
                add_genius_mixes=("rock",),
            ),
            lambda _: None,
            Event(),
        )
        saved = device.save(created)
        assert saved.active is not None, saved.issues
        active = saved.active
        if not owned:
            (device.root / str(mix_service.MIX_STATE_PATH)).unlink()
            active = device.coordinator.select_device(
                device.coordinator.discover_devices().candidates[0].id
            )
            assert not active.genius_mix_state.entries
        mix = active.genius.collections[0]
        removed = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                active.library,
                active,
                2,
                2,
                remove_genius_collections=(mix.collection_id,),
            ),
            lambda _: None,
            Event(),
        )
        assert removed.result.prepared is not None, removed.result.issues
        result = device.save(removed)
        assert result.active is not None, result.issues
        assert not result.active.genius.collections
        assert not result.active.genius_mix_state.entries
        reloaded = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert not reloaded.genius.collections
        assert not reloaded.genius_mix_state.entries
    finally:
        device.coordinator.close()


def test_sync_uses_saved_settings_rotates_and_reloads_ownership(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=tuple(
                replace(t, genre=genre)
                for t, genre in zip(
                    active.library.tracks, ("Rock", "Jazz"), strict=True
                )
            ),
        )
        review = device.prepare(desired)
        saved = device.coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        active = saved.active
        # SettingsService keeps a newer confirmed settings revision than the
        # immutable Active iPod after a settings-only save.
        device.coordinator.save_settings(
            active, active.settings, {GENIUS_MIX_POLICY.key: MixPolicy(1, 1).encode()}
        )
        executor = SyncExecutor(device.coordinator)
        with patch_current_time(
            Instant.from_timestamp(1_800_000_000), keep_ticking=False
        ):
            first = executor.execute(_refresh_request(active), lambda _: None, Event())
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None
        initial = first.active.genius_mix_state.entries[0]
        assert initial.added_at == 1_800_000_000
        with patch_current_time(
            Instant.from_timestamp(1_800_086_401), keep_ticking=False
        ):
            second = executor.execute(
                _refresh_request(first.active), lambda _: None, Event()
            )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None
        rotated = second.active.genius_mix_state.entries[0]
        assert rotated.container_id != initial.container_id
        assert rotated.definition_key != initial.definition_key
        assert len(second.active.genius.collections) == 1
        reloaded = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert reloaded.genius_mix_state == second.active.genius_mix_state
    finally:
        device.coordinator.close()


def test_cancel_and_changed_settings_cannot_publish_mix_ownership(
    mix_device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = mix_device
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=tuple(replace(t, genre="Rock") for t in active.library.tracks),
        )
        request = LibraryPreparationRequest(
            desired,
            active,
            1,
            1,
            regenerate_genius=True,
            add_genius_mixes=("rock",),
            rotate_genius_mixes=True,
        )
        review = device.coordinator.prepare_library(request, lambda _: None, Event())
        assert review.result.prepared is not None, review.result.issues
        cancelled = Event()
        cancelled.set()
        with pytest.raises(PreparationCancelledError):
            device.coordinator.save_library(review, active, lambda _: None, cancelled)
        assert not (device.root / str(mix_service.MIX_STATE_PATH)).exists()
        device.assert_original()
        review = device.coordinator.prepare_library(request, lambda _: None, Event())
        assert review.result.prepared is not None
        device.coordinator.save_settings(
            active, active.settings, {GENIUS_MIX_POLICY.key: MixPolicy(1, 7).encode()}
        )
        result = device.coordinator.save_library(
            review, active, lambda _: None, Event()
        )
        assert result.active is None
        assert not (device.root / str(mix_service.MIX_STATE_PATH)).exists()
        device.assert_original()
    finally:
        device.coordinator.close()
