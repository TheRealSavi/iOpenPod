"""Ordinary Library removals keep the persisted correlation helper in step."""

import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import (
    Device,
    build_device,
    without_first,
)
from tests.iOpenPod.app.test_media_lyrics import fixture

from iOpenPod.app import library_sync_helper as helper
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    SyncDetails,
    SyncedTrack,
)
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    PreparationCancelledError,
)
from iOpenPod.app.services import device_coordinator
from iPodDB.library import IPodLibrary
from iPodDB.library.writing import IssueSeverity
from storage import (
    DevicePath,
    FilesystemSession,
    FlushResult,
    StorageOperationError,
)


def seed_helper(device: Device) -> Path:
    device.coordinator.publish_sync_success(
        device.active,
        None,
        tuple(
            SyncedTrack(
                DevicePath(track.metadata.location),
                "1,2,3",
                SyncDetails(
                    "2026-10-01",
                    f"Music/{track.track_id}.flac",
                    123,
                    456,
                    "flac",
                    "m4a",
                    True,
                    host_tag_sha256="a" * 64,
                    stream_selection_sha256="b" * 64,
                ),
                track_id=track.track_id,
            )
            for track in device.active.library.tracks
        ),
    )
    return device.root / str(LIBRARY_SYNC_HELPER_PATH)


def prepare_removal(
    device: Device, *, discard: bool = True, remove_all: bool = False
) -> LibraryReview:
    desired = without_first(device)
    if remove_all:
        desired = replace(
            desired,
            tracks=(),
            playlists=tuple(replace(item, entries=()) for item in desired.playlists),
        )
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            desired,
            device.active,
            1,
            1,
            delete_omissions=True,
            discard_removed_track_media=discard,
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    return review


@pytest.mark.parametrize("discard", [False, True])
@pytest.mark.parametrize("shared_media", [False, True])
@pytest.mark.parametrize("remove_all", [False, True])
def test_ordinary_track_removal_prunes_persisted_sync_helper(
    tmp_path: Path, discard: bool, shared_media: bool, remove_all: bool
) -> None:
    device = build_device(tmp_path, shared_media=shared_media)
    try:
        before = device.active
        removed, retained = before.library.tracks
        helper_path = seed_helper(device)
        original_bytes = helper_path.read_bytes()
        original = json.loads(original_bytes)
        review = prepare_removal(device, discard=discard, remove_all=remove_all)
        assert helper_path.read_bytes() == original_bytes
        saved = device.coordinator.save_library(review, before, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert not saved.issues
        assert saved.recovery_path == ""
        assert saved.active.library.tracks == (() if remove_all else (retained,))
        assert (device.root / removed.metadata.location).exists() == (
            shared_media and not remove_all
        )
        current = json.loads(helper_path.read_bytes())
        assert current["tracks"] == [
            record
            for record in original["tracks"]
            if not remove_all and record["track_id"] == retained.track_id
        ]
        assert current["library_sha256"] == saved.active.database_fingerprint.sha256
        with device.coordinator.sync_session(saved.active) as session:
            loaded, issue = helper._load_helper(session)  # pyright: ignore[reportPrivateUsage]
        assert issue is None
        assert len(loaded.tracks) == int(not remove_all)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("failure", ["changed_library", "cancelled"])
def test_unsaved_removal_leaves_helper_unchanged(tmp_path: Path, failure: str) -> None:
    device = build_device(tmp_path)
    try:
        before = device.active
        helper_path = seed_helper(device)
        original = helper_path.read_bytes()
        review = prepare_removal(device)
        cancelled = Event()
        if failure == "changed_library":
            database = device.root / "iPod_Control/iTunes/iTunesDB"
            database.write_bytes(database.read_bytes() + b"external change")
        else:
            cancelled.set()
        if failure == "cancelled":
            with pytest.raises(PreparationCancelledError):
                device.coordinator.save_library(
                    review, before, lambda _: None, cancelled
                )
        else:
            saved = device.coordinator.save_library(
                review, before, lambda _: None, cancelled
            )
            assert saved.active is None
        assert helper_path.read_bytes() == original
        assert (device.root / before.library.tracks[0].metadata.location).exists()
    finally:
        device.coordinator.close()


def test_removal_without_helper_does_not_create_one(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        review = prepare_removal(device)
        saved = device.coordinator.save_library(
            review, device.active, lambda _: None, Event()
        )
        assert saved.active is not None, saved.issues
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("failure", ["invalid", "write"])
def test_helper_failure_warns_without_reverting_saved_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    device = build_device(tmp_path)
    try:
        before = device.active
        helper_path = seed_helper(device)
        if failure == "invalid":
            helper_path.write_bytes(b"invalid helper must be preserved")
        else:

            def reject_publish(*args: object, **kwargs: object) -> None:
                raise StorageOperationError("helper write failed")

            monkeypatch.setattr(
                device_coordinator, "publish_sync_helper", reject_publish
            )
        original = helper_path.read_bytes()
        review = prepare_removal(device)
        saved = device.coordinator.save_library(review, before, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert helper_path.read_bytes() == original
        assert not (device.root / before.library.tracks[0].metadata.location).exists()
        assert saved.recovery_path == ""
        assert [issue.code for issue in saved.issues] == ["save.sync_helper_failed"]
        assert saved.issues[0].severity is IssueSeverity.WARNING
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        assert IPodLibrary(database.read_bytes()).snapshot == saved.active.library
    finally:
        device.coordinator.close()


def test_removal_with_retag_prunes_helper_in_its_recoverable_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    try:
        before = device.active
        helper_path = seed_helper(device)
        original = json.loads(helper_path.read_bytes())
        desired = without_first(device)
        retained = desired.tracks[0]
        desired = replace(
            desired,
            tracks=(
                replace(retained, metadata=replace(retained.metadata, lyrics="New")),
            ),
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(desired, before, 1, 1, delete_omissions=True),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        finalize = FilesystemSession.finalize_committed_transaction
        verified = False

        def verify_recovery(
            session: FilesystemSession, path: DevicePath
        ) -> FlushResult:
            nonlocal verified
            recovery = session.inspect_transaction(path)
            cached = next(
                file for file in recovery.files if file.path == LIBRARY_SYNC_HELPER_PATH
            )
            assert cached.fingerprint == session.fingerprint(LIBRARY_SYNC_HELPER_PATH)
            verified = True
            return finalize(session, path)

        monkeypatch.setattr(
            FilesystemSession, "finalize_committed_transaction", verify_recovery
        )
        saved = device.coordinator.save_library(review, before, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert not saved.issues
        assert verified
        assert saved.recovery_path == ""
        current = json.loads(helper_path.read_bytes())
        assert len(current["tracks"]) == 1
        assert current["tracks"][0]["track_id"] == retained.track_id
        original_retained = next(
            record
            for record in original["tracks"]
            if record["track_id"] == retained.track_id
        )
        assert current["tracks"][0]["sync"] == original_retained["sync"]
    finally:
        device.coordinator.close()
