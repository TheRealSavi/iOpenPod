"""Mix ownership and native collections are one recoverable publication."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_genius import (
    _refresh_request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app import genius_mixes
from iOpenPod.app.genius_mixes import GENIUS_MIX_POLICY, MixPolicy
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
)
from iOpenPod.app.services import genius_mixes as mix_service
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor


def test_track_deletion_removes_only_the_emptied_mix_and_its_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = build_device(tmp_path, model="MD479", compressed_database=True)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The common virtual fixture has two Tracks; catalog eligibility is tested
    # separately with the real ten-Track minimum.
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = build_device(tmp_path, model="MD479", compressed_database=True)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: bool
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = build_device(tmp_path, model="MD479", compressed_database=True)
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
                regenerate_genius=True,
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    monkeypatch.setattr(mix_service, "time", lambda: 1_800_000_000)
    device = build_device(tmp_path, model="MD479", compressed_database=True)
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
        first = executor.execute(_refresh_request(active), lambda _: None, Event())
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None
        initial = first.active.genius_mix_state.entries[0]
        assert initial.added_at == 1_800_000_000
        monkeypatch.setattr(mix_service, "time", lambda: 1_800_086_401)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = build_device(tmp_path, model="MD479", compressed_database=True)
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
