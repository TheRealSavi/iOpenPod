"""Sidecar projection, publication, staleness and recovery on virtual devices."""

import plistlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg, stats

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateIssueCode
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinationError,
    DeviceLibraryLoadError,
    SyncRecoveryRequiredError,
)
from iPodDB.library import IPodLibrary
from storage import DevicePath, FilesystemSession


def test_discovery_is_read_only_and_selection_commits_history_and_otg_once(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    files = {
        "Play Counts": counts(),
        "OTGPlaylistInfo": otg((1, 0, 1)),
        "OTGPlaylistInfo_2": otg((0,)),
    }
    try:
        for name, data in files.items():
            (directory / name).write_bytes(data)
        candidate = device.coordinator.discover_devices().candidates[0]
        device.assert_original()
        for name, data in files.items():
            assert (directory / name).read_bytes() == data
        selected = device.coordinator.select_device(candidate.id)
        assert selected is device.active
        snapshot = device.active.library
        assert snapshot.tracks[0].play_count == 3
        assert snapshot.playlists[-2].track_ids == (
            snapshot.tracks[1].track_id,
            snapshot.tracks[0].track_id,
            snapshot.tracks[1].track_id,
        )
        for name, data in files.items():
            assert not (directory / name).exists()
            assert (directory / (name + ".bak")).read_bytes() == data
        persisted = IPodLibrary((directory / "iTunesDB").read_bytes())
        assert persisted.snapshot.tracks[0].play_count == 3
        assert persisted.snapshot.playlists == snapshot.playlists
        assert not tuple(
            (device.root / ".iopenpod-recovery").glob("*/transaction.json")
        )
        committed = (directory / "iTunesDB").read_bytes()
        reloaded = device.coordinator.select_device(device.active.candidate.id)
        assert reloaded.library.tracks[0].play_count == 3
        assert len(reloaded.library.playlists) == len(snapshot.playlists)
        assert (directory / "iTunesDB").read_bytes() == committed
        # A later ordinary save cannot import the retired delta or playlists again.
        review = device.prepare(replace(reloaded.library, device_name="Sidecar test"))
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].play_count == 3
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("kind", ["stats24", "stats32", "plist"])
def test_other_playback_formats_publish_through_the_same_transaction(
    tmp_path: Path, kind: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        track = device.active.library.tracks[1]
        assert track.ipod is not None
        if kind == "plist":
            name = "PlayCounts.plist"
            data = plistlib.dumps(
                {"tracks": [{"persistentID": track.ipod.db_track_id, "playCount": 5}]},
                fmt=plistlib.FMT_BINARY,
            )
        else:
            name = "iTunesStats"
            data = stats(3 if kind == "stats24" else 4)
        (directory / name).write_bytes(data)
        device.coordinator.select_device(device.active.candidate.id)
        assert device.active.library.tracks[1].play_count == 5
        persisted = IPodLibrary((directory / "iTunesDB").read_bytes())
        assert persisted.snapshot.tracks[1].play_count == 5
        assert (directory / (name + ".bak")).read_bytes() == data
        assert not (directory / name).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "phase", ["before_review", "after_review", "save.storage.prepared"]
)
@pytest.mark.parametrize("mutation", ["change", "delete", "new_file"])
def test_changed_loaded_evidence_never_publishes_stale_totals(
    tmp_path: Path, phase: str, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    path = directory / "Play Counts"
    try:
        path.write_bytes(counts())

        def mutate() -> None:
            if mutation == "change":
                path.write_bytes(counts(((7, 0, 0),), width=12))
            elif mutation == "delete":
                path.unlink()
            else:
                (directory / "PlayCounts.plist").write_bytes(
                    plistlib.dumps({"tracks": []})
                )

        prepare = device.coordinator.prepare_library
        save = device.coordinator.save_library

        def prepare_with_mutation(
            request: LibraryPreparationRequest,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibraryReview:
            if phase == "before_review":
                mutate()
            review = prepare(request, progress, cancelled)
            if phase == "after_review":
                mutate()
            return review

        def save_with_mutation(
            review: LibraryReview,
            expected: ActiveIPod,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibrarySaveResult:
            def observed(event: WriteProgress) -> None:
                progress(event)
                if event.phase == phase:
                    mutate()

            return save(review, expected, observed, cancelled)

        monkeypatch.setattr(
            device.coordinator, "prepare_library", prepare_with_mutation
        )
        monkeypatch.setattr(device.coordinator, "save_library", save_with_mutation)
        with pytest.raises((DeviceLibraryLoadError, SyncRecoveryRequiredError)):
            device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert device.coordinator.discovery.active_candidate_id is None
        device.assert_original()
        assert not (directory / "Play Counts.bak").exists()
    finally:
        device.coordinator.close()


def test_cleanup_failure_keeps_committed_selection_and_recovery_restores_all_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    data = counts()
    try:
        (directory / "Play Counts").write_bytes(data)
        (directory / "Play Counts.bak").write_bytes(b"previous backup")

        def fail_cleanup(_session: FilesystemSession, _path: DevicePath) -> None:
            raise OSError("Recovery files are temporarily unavailable")

        with monkeypatch.context() as fault:
            fault.setattr(
                FilesystemSession, "finalize_committed_transaction", fail_cleanup
            )
            selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected.library.tracks[0].play_count == 3
        assert any(
            issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
            for issue in selected.candidate.issues
        )
        recovered = device.coordinator.recover_sync_journal(
            device.coordinator.sync_cleanup_path
        )
        device.assert_original()
        assert recovered.library.tracks[0].play_count == 0
        assert (directory / "Play Counts").read_bytes() == data
        assert (directory / "Play Counts.bak").read_bytes() == b"previous backup"
    finally:
        device.coordinator.close()


def test_malformed_sidecar_blocks_selection_without_committing_other_valid_sidecars(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/Play Counts"
    try:
        path.write_bytes(b"malformed history")
        otg_path = path.with_name("OTGPlaylistInfo")
        otg_path.write_bytes(otg((0,)))
        with pytest.raises(DeviceLibraryLoadError, match="Play Counts"):
            device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert path.read_bytes() == b"malformed history"
        assert otg_path.read_bytes() == otg((0,))
        assert not otg_path.with_suffix(".bak").exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_track_removal_commits_correct_history_and_otg_membership(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        (directory / "Play Counts").write_bytes(
            counts(((3, 0, 0), (8, 0, 0)), width=12)
        )
        (directory / "OTGPlaylistInfo").write_bytes(otg((1, 0, 1)))
        device.coordinator.select_device(device.active.candidate.id)
        # Any later edit and restoration now starts from the committed history.
        for relative in device.original:
            device.original[relative] = (device.root / relative).read_bytes()
        snapshot = device.active.library
        survivor = snapshot.tracks[1]
        desired = replace(
            snapshot,
            tracks=(survivor,),
            playlists=tuple(
                replace(
                    p,
                    entries=tuple(
                        e for e in p.entries if e.track_id == survivor.track_id
                    ),
                )
                for p in snapshot.playlists
            ),
        )
        review = device.prepare(desired, delete=True)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].play_count == 8
        assert saved.active.library.playlists[-1].track_ids == (survivor.track_id,) * 2
        assert not (directory / "Play Counts").exists()
        assert not (directory / "OTGPlaylistInfo").exists()
        device.restore(saved.recovery_path)
        assert not (directory / "Play Counts").exists()
        assert not (directory / "OTGPlaylistInfo").exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("choice", ["restore", "keep", "disconnect_restore"])
def test_interrupted_selection_requires_recovery_and_does_not_reconsume_on_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        (directory / "Play Counts").write_bytes(counts())
        save = device.coordinator.save_library

        def interrupted_save(
            review: LibraryReview,
            expected: ActiveIPod,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibrarySaveResult:
            def observed(event: WriteProgress) -> None:
                progress(event)
                if (
                    event.phase == "save.storage.publishing"
                    and event.current_item == "iPod_Control/iTunes/iTunesDB"
                ):
                    if choice == "disconnect_restore":
                        device.platform.disconnect(device.root)
                    else:
                        raise OSError(
                            "Publication interrupted after database replacement"
                        )

            return save(review, expected, observed, cancelled)

        with monkeypatch.context() as fault:
            fault.setattr(device.coordinator, "save_library", interrupted_save)
            with pytest.raises(SyncRecoveryRequiredError) as failure:
                device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert device.coordinator.discovery.active_candidate_id is None
        assert (directory / "Play Counts").read_bytes() == counts()
        assert (
            IPodLibrary((directory / "iTunesDB").read_bytes())
            .snapshot.tracks[0]
            .play_count
            == 3
        )
        if choice == "disconnect_restore":
            device.platform.reconnect(device.root)
        if choice == "keep":
            recovered = device.coordinator.keep_sync_contents(
                failure.value.recovery_path
            )
            assert recovered.library.tracks[0].play_count == 3
        else:
            recovered = device.coordinator.recover_sync_journal(
                failure.value.recovery_path
            )
            device.assert_original()
            assert recovered.library.tracks[0].play_count == 0
        assert (directory / "Play Counts").read_bytes() == counts()
    finally:
        device.coordinator.close()


def test_read_only_device_with_pending_history_cannot_publish_a_pending_library(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/Play Counts"
    try:
        path.write_bytes(counts())
        device.platform.set_writable(device.root, False)
        candidate = device.coordinator.discover_devices().candidates[0]
        with pytest.raises(DeviceCoordinationError):
            device.coordinator.select_device(candidate.id)
        assert device.coordinator.active_ipod is None
        device.assert_original()
        assert path.read_bytes() == counts()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("kind", ["absent", "orphan", "unknown", "empty_otg"])
def test_selection_preserves_database_without_known_changes(
    tmp_path: Path, kind: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    files = {
        "orphan": ("OTGPlaylistInfo_2", otg((0,))),
        "unknown": ("On-The-Go-future", b"unrecognized firmware data"),
        "empty_otg": ("OTGPlaylistInfo", otg(())),
    }
    try:
        if kind in files:
            name, data = files[kind]
            (directory / name).write_bytes(data)
        selected = device.coordinator.select_device(device.active.candidate.id)
        device.assert_original()
        assert selected.library.tracks[0].play_count == 0
        if kind in files:
            name, data = files[kind]
            if kind == "empty_otg":
                assert not (directory / name).exists()
                assert (directory / (name + ".bak")).read_bytes() == data
            else:
                assert (directory / name).read_bytes() == data
    finally:
        device.coordinator.close()
