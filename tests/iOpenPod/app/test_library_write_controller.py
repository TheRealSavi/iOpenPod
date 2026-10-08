"""Preparation runs off-thread and cannot publish obsolete or partial output."""

import base64
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QTreeWidget
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iPodDB.library.test_video_flags import video_source
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.core.settings.definitions import (
    DRAFT_ALL_CHANGES,
    MANAGE_VOLUME_PRESENTATION,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.library_write_controller import (
    LibraryWriteController,
    PreparationState,
)
from iOpenPod.app.library_write_inspection import (
    InspectionLimits,
    inspect_library_write,
)
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.GUI.dialogs.library_review import LibraryReviewDialog
from iPodDB.library import (
    IPodLibrary,
    LibrarySnapshot,
    PlaylistKind,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
    TrackFieldEdit,
)
from iPodDB.library.writing import IssueSeverity, LibraryWriteResult, WriteIssue
from storage import (
    DevicePath,
    FilesystemSession,
    FlushResult,
    HardwareIdentifiers,
    Storage,
    StorageOperationError,
    TransactionDurabilityPendingError,
    TransactionFailureFacts,
    TransactionState,
)
from storage.testing import VirtualStoragePlatform


# Pylance leaves pytest's optional ScopeName/Config annotations unresolved here.
@pytest.fixture
def track_model() -> TrackTableModel:
    return TrackTableModel()


@pytest.fixture  # pyright: ignore[reportUnknownMemberType]
def session(
    tmp_path: Path,
    track_model: TrackTableModel,
) -> Iterator[tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path]]:
    root = tmp_path / "ipod"
    metadata = root / "iPod_Control" / "Device"
    metadata.mkdir(parents=True)
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    database.parent.mkdir()
    database.write_bytes(library().serialize().itunes)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nFirewireGuid: 000A270012345678\n", encoding="utf-8"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
    )
    coordinator = DeviceCoordinator(
        Storage(platform, writer_lock_directory=tmp_path / "locks")
    )
    discovery = coordinator.discover_devices()
    active = coordinator.select_device(discovery.candidates[0].id)
    devices = DeviceController(
        coordinator,
        track_model,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    workspace = LibraryWorkspace()
    workspace.load(active.library)
    workspace.rename(10, "Reviewed")
    try:
        yield coordinator, devices, workspace, database
    finally:
        devices.shutdown()


def manual_settings() -> SettingsService:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(DRAFT_ALL_CHANGES, True)
    return settings


@pytest.mark.parametrize("automatic", [False, True])
def test_successful_save_does_not_offer_cleanup_after_reload(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    automatic: bool,
) -> None:
    coordinator, devices, workspace, database = session
    settings = (
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
        if automatic
        else manual_settings()
    )
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    try:
        if not automatic:
            controller.prepare()
            wait_for(lambda: controller.state is PreparationState.READY)
            controller.save()
            wait_for(lambda: controller.state is not PreparationState.SAVING)
            assert controller.state is PreparationState.SAVED, controller.save_result
        else:
            wait_for(lambda: controller.state is PreparationState.SAVED)
        assert not workspace.dirty
        assert controller.save_result is not None
        assert controller.save_result.recovery_path == ""
        assert not tuple(
            database.parents[2].glob(".iopenpod-recovery/*/transaction.json")
        )
        saved_bytes = database.read_bytes()
        active = coordinator.active_ipod
        assert active is not None
        coordinator.select_device(active.candidate.id)
        assert coordinator.sync_cleanup_path == ""
        assert database.read_bytes() == saved_bytes
    finally:
        controller.shutdown()


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("failure", ["delete", "before_flush", "after_flush"])
def test_cleanup_failure_preserves_successful_library_save(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    automatic: bool,
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    finalize = FilesystemSession.finalize_committed_transaction

    def fail_cleanup(storage: FilesystemSession, path: DevicePath) -> FlushResult:
        if failure == "delete":
            raise StorageOperationError("Recovery file is locked")
        if failure == "after_flush":
            finalize(storage, path)
        raise TransactionDurabilityPendingError(
            "Device flush failed",
            TransactionFailureFacts(path, TransactionState.COMMITTED, True, True),
        )

    monkeypatch.setattr(
        FilesystemSession, "finalize_committed_transaction", fail_cleanup
    )
    settings = (
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
        if automatic
        else manual_settings()
    )
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    warnings = QSignalSpy(controller.automaticSaveWarning)
    failures = QSignalSpy(controller.automaticSaveFailed)
    try:
        if automatic:
            wait_for(lambda: controller.state is PreparationState.SAVED)
        else:
            controller.prepare()
            wait_for(lambda: controller.state is PreparationState.READY)
            controller.save()
            wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        assert warnings.count() == int(automatic)
        assert failures.count() == 0
        assert not workspace.dirty and not workspace.locked and not devices.busy
        assert database.read_bytes() != original
        result = controller.save_result
        assert result is not None and result.active is not None
        assert (
            result.active.library == IPodLibrary.parse(database.read_bytes()).snapshot
        )
        issue = result.issues[-1]
        assert issue.severity is IssueSeverity.WARNING
        if failure == "after_flush":
            assert issue.code == "save.cleanup_flush_pending"
            assert result.recovery_path == ""
            assert not tuple(
                database.parents[2].glob(".iopenpod-recovery/*/transaction.json")
            )
        else:
            assert issue.code == "save.cleanup_pending"
            journal = database.parents[2] / result.recovery_path
            assert json.loads(journal.read_bytes())["state"] == "committed"
        assert (
            "Recovery file is locked" if failure == "delete" else "Device flush failed"
        ) in issue.detail
    finally:
        controller.shutdown()


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        # Yield Python execution to the worker as well as pumping Qt events.
        sleep(0.005)
    assert predicate()


def finish_workers(controller: LibraryWriteController) -> None:
    pool = controller.findChild(QThreadPool)
    assert pool is not None and pool.waitForDone(5000)
    APPLICATION.processEvents()


def test_drive_appearance_change_retires_review_and_reprepares_rename(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    controller = context.library_write_controller
    try:
        context.settings.set_global(DRAFT_ALL_CHANGES, True)
        workspace = context.library_workspace
        workspace.load(device.active.library)
        old_companion = (device.root / "autorun.inf").read_bytes()
        old_label = device.platform.inspect(device.root).volume.label
        workspace.rename_device("Renamed", workspace.edit_revision)
        controller.prepare()
        wait_for(lambda: controller.state is PreparationState.READY)
        context.settings.set_global(MANAGE_VOLUME_PRESENTATION, False)
        assert controller.state is PreparationState.STALE
        assert not controller.can_save and controller.can_prepare
        controller.prepare()
        wait_for(lambda: controller.state is PreparationState.READY)
        controller.save()
        wait_for(lambda: controller.state is PreparationState.SAVED)
        assert device.active.library.device_name == "Renamed"
        assert (device.root / "autorun.inf").read_bytes() == old_companion
        assert device.platform.inspect(device.root).volume.label == old_label
    finally:
        context.shutdown()


def test_device_busy_changes_notify_review_without_forwarding_boolean(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    coordinator, devices, workspace, _ = session
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    notifications = QSignalSpy(controller.changed)
    try:
        for busy in (True, False):
            devices.busyChanged.emit(busy)
        assert capsys.readouterr().err == ""
        assert notifications.count() == 2
        assert controller.state is PreparationState.IDLE
        assert controller.review is None and workspace.dirty
    finally:
        controller.shutdown()


def test_read_only_device_reservation_blocks_save_but_not_review_preparation(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )

    try:
        assert devices.begin_read_only_operation() is True
        assert controller.can_prepare
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.can_save is False
        controller.save()
        assert controller.state is PreparationState.READY
        assert database.read_bytes() == original

        devices.finish_read_only_operation()
        assert controller.can_save is True
    finally:
        devices.finish_read_only_operation()
        controller.shutdown()


def test_save_repairs_existing_video_playback_flags_in_the_reviewed_request(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = video_source(video=True).serialize().itunes
    database.write_bytes(original)
    assert devices.reload_active_ipod()
    wait_for(lambda: not devices.busy)
    active = devices.active_ipod
    assert active is not None
    workspace.load(active.library)
    workspace.rename(10, "Reviewed")
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        assert not workspace.tracks[0].metadata.skip_shuffle
        assert not workspace.tracks[0].metadata.remember_position

        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)

        assert controller.state is PreparationState.READY, controller.review
        assert controller.request is not None
        reviewed = controller.request.snapshot.tracks[0]
        assert reviewed.metadata.skip_shuffle and reviewed.metadata.remember_position
        assert database.read_bytes() == original
        assert not workspace.tracks[0].metadata.skip_shuffle

        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)

        assert str(controller.state) == PreparationState.SAVED.value, (
            controller.save_result
        )
        saved = IPodLibrary(database.read_bytes()).snapshot.tracks[0]
        assert saved.metadata.skip_shuffle and saved.metadata.remember_position
    finally:
        controller.shutdown()


def test_review_prepares_signed_output_and_does_not_save_or_clear_draft(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    dialog = LibraryReviewDialog(controller)
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.state is PreparationState.READY, controller.review
        assert (
            controller.review is not None
            and controller.review.result.prepared is not None
        )
        assert (
            controller.review.result.prepared.snapshot.playlists[0].name == "Reviewed"
        )
        assert database.read_bytes() == original
        assert workspace.dirty
        assert any(
            "Prepared for review" in label.text()
            for label in dialog.findChildren(QLabel)
        )
        tree = dialog.findChild(QTreeWidget, "libraryReviewItems")
        assert tree is not None and tree.topLevelItemCount() == 4
        assert any(
            i.code == "source.master_membership"
            for i in controller.review.result.issues
        )
        assert "Library write request attempt=1 workspace_generation=" in caplog.text
        assert "Library review received attempt=1 prepared=True" in caplog.text
        assert "Library review issue attempt=1" in caplog.text
        assert "source.master_membership" in caplog.text
        workspace.rename(10, "Edited again")
        assert str(controller.state) == PreparationState.STALE.value
        wait_for(lambda: controller.review is None)
    finally:
        dialog.deleteLater()
        controller.shutdown()


def test_review_dialog_discards_the_entire_library_draft(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    dialog = LibraryReviewDialog(controller)
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.state is PreparationState.READY
        discard = dialog.findChild(QPushButton, "discardLibraryChanges")
        assert discard is not None and discard.isEnabled() and not discard.isHidden()

        discard.click()

        assert not workspace.dirty
        playlist = workspace.playlist(10)
        assert playlist is not None and playlist.name == "Playlist"
        assert str(controller.state) == PreparationState.IDLE.value
        assert controller.request is None and controller.review is None
        assert discard.isHidden()
    finally:
        dialog.deleteLater()
        controller.shutdown()


class DelayedService:
    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibrarySaveResult:
        raise AssertionError("This test does not save")

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview:
        self.entered.set()
        self.release.wait(3)
        # Deliberately simulate an old worker that completes after cancellation.
        return LibraryReview(
            None,
            LibraryWriteResult(
                (
                    WriteIssue(
                        "test.blocked",
                        "A recoverable problem",
                        subject="playlist",
                        record_id=10,
                    ),
                )
            ),
        )


@pytest.mark.parametrize("edit", [False, True])
def test_cancellation_and_new_edits_discard_late_results(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    edit: bool,
) -> None:
    _, devices, workspace, _ = session
    service = DelayedService()
    controller = LibraryWriteController(service, workspace, devices, manual_settings())
    try:
        controller.prepare()
        wait_for(service.entered.is_set)
        if edit:
            workspace.rename(10, "Changed during preparation")
        else:
            controller.cancel()
        service.release.set()
        finish_workers(controller)
        assert controller.state is (
            PreparationState.STALE if edit else PreparationState.CANCELLED
        )
        assert controller.review is None and workspace.dirty
    finally:
        service.release.set()
        controller.shutdown()


def test_changed_source_is_actionable_and_never_returns_output(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    database.write_bytes(database.read_bytes() + b"external change")
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.state is PreparationState.BLOCKED
        assert controller.review is not None
        assert controller.review.result.issues[0].code == "source.unavailable"
        assert controller.review.result.prepared is None and workspace.dirty
    finally:
        controller.shutdown()


def test_application_preparation_does_not_implicitly_authorize_omission_deletions(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    desired = replace(workspace.desired_snapshot(), playlists=())
    active = devices.active_ipod
    assert active is not None
    progress: list[WriteProgress] = []
    review = coordinator.prepare_library(
        LibraryPreparationRequest(
            desired, active, workspace.generation, workspace.revision
        ),
        progress.append,
        threading.Event(),
    )
    assert review.plan is not None and review.plan.blocked
    assert review.result.prepared is None
    assert any(
        i.code == "draft.deletion_not_enabled" and i.record_id == 10
        for i in review.result.issues
    )
    assert database.read_bytes() == original and workspace.dirty


def test_connection_change_discards_an_in_flight_result(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _, devices, workspace, _ = session
    service = DelayedService()
    controller = LibraryWriteController(service, workspace, devices, manual_settings())
    try:
        controller.prepare()
        wait_for(service.entered.is_set)
        devices.activeIPodChanged.emit(None)
        service.release.set()
        finish_workers(controller)
        assert controller.state is PreparationState.STALE
        assert controller.review is None and workspace.dirty
    finally:
        service.release.set()
        controller.shutdown()


class BrokenService(DelayedService):
    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview:
        raise RuntimeError("technical failure for the log")


def test_unexpected_failure_is_logged_and_keeps_draft(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, devices, workspace, _ = session
    controller = LibraryWriteController(
        BrokenService(), workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.state is PreparationState.FAILED and controller.review
        assert controller.review.result.issues[0].code == "preparation.internal_error"
        assert "technical failure for the log" in caplog.text
        assert "technical failure" not in controller.review.result.issues[0].message
        assert workspace.dirty
    finally:
        controller.shutdown()


def test_review_groups_diagnostics_and_exposes_details_and_navigation(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    error = WriteIssue(
        "track.bad_value",
        "Correct this value",
        subject="track",
        record_id=1,
        field="year",
        detail="binary detail",
        offset=123,
    )
    warning = WriteIssue(
        "playlist.retained",
        "Retained source data",
        severity=IssueSeverity.WARNING,
        subject="playlist",
        record_id=10,
    )
    controller.review = LibraryReview(None, LibraryWriteResult((error, warning)))
    controller.state = PreparationState.BLOCKED
    dialog = LibraryReviewDialog(controller)
    requested: list[tuple[str, int]] = []

    def record_request(subject: str, identity: int) -> None:
        requested.append((subject, identity))

    dialog.recordRequested.connect(record_request)
    try:
        tree = dialog.findChild(QTreeWidget, "libraryReviewItems")
        details = dialog.findChild(QPlainTextEdit, "libraryReviewDetails")
        assert tree is not None and details is not None
        assert tree.topLevelItemCount() == 2
        errors = tree.topLevelItem(0)
        warnings = tree.topLevelItem(1)
        assert errors is not None and warnings is not None
        assert errors.text(0) == "Errors (1)"
        assert warnings.text(0) == "Warnings (1)"
        item = errors.child(0)
        assert item is not None
        assert item.data(0, Qt.ItemDataRole.UserRole) == error
        tree.setCurrentItem(item)
        assert (
            "binary detail" in details.toPlainText() and "123" in details.toPlainText()
        )
        tree.itemDoubleClicked.emit(item, 0)
        assert requested == [("track", 1)]
    finally:
        dialog.deleteLater()
        controller.shutdown()


def test_save_commits_verified_playlist_output_and_adopts_new_source(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.can_save, controller.review
        controller.save()
        assert workspace.locked and devices.busy
        with pytest.raises(ValueError, match="save"):
            workspace.rename(10, "Racing edit")
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        assert not workspace.dirty and not workspace.locked and not devices.busy
        assert database.read_bytes() != original
        assert devices.active_ipod is not None
        assert workspace.snapshot is devices.active_ipod.library
        assert controller.save_result is not None
        assert controller.save_result.recovery_path == ""
        assert not tuple(
            database.parents[2].glob(".iopenpod-recovery/*/transaction.json")
        )
        # The next edit is bound to the newly committed source.
        workspace.rename(10, "Saved twice")
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.can_save, controller.review
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
    finally:
        controller.shutdown()


def test_metadata_and_device_rename_save_together_and_clean_recovery(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    track_model: TrackTableModel,
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    before = workspace.tracks
    track_model.reset_tracks(before)
    workspace.rename_device("Metadata Test iPod", workspace.edit_revision)
    workspace.apply_track_edits(
        (
            TrackUpdate(
                before[0].track_id,
                (
                    TrackFieldEdit("title", "Edited title"),
                    TrackFieldEdit("artist", "A different artist"),
                    TrackFieldEdit("album", "Another album"),
                    TrackFieldEdit("metadata.sort_artist", "Different artist, A"),
                    TrackFieldEdit("rating", 80),
                    TrackFieldEdit("metadata.comment", "Edited comment"),
                ),
            ),
        ),
        workspace.edit_revision,
    )
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.can_save, controller.review
        assert database.read_bytes() == original and workspace.dirty
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        reloaded = IPodLibrary.parse(database.read_bytes()).snapshot
        assert reloaded == workspace.snapshot
        assert track_model.tracks == reloaded.tracks
        assert reloaded.device_name == "Metadata Test iPod"
        assert reloaded.tracks[0].title == "Edited title"
        assert reloaded.tracks[0].artist == "A different artist"
        assert reloaded.tracks[0].album == "Another album"
        assert reloaded.tracks[0].rating == 80
        assert reloaded.tracks[0].metadata.comment == "Edited comment"
        assert reloaded.tracks[0].metadata.location == before[0].metadata.location
        assert reloaded.tracks[1:] == before[1:]
        assert not workspace.dirty
        assert controller.save_result is not None
        assert controller.save_result.recovery_path == ""
        assert not tuple(
            database.parents[2].glob(".iopenpod-recovery/*/transaction.json")
        )
    finally:
        controller.shutdown()


def test_save_rejects_external_change_and_retains_draft(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        changed = database.read_bytes() + b"external"
        database.write_bytes(changed)
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVE_FAILED
        assert workspace.dirty and not workspace.locked and not devices.busy
        assert database.read_bytes() == changed
        assert (
            controller.save_result
            and controller.save_result.issues[0].code == "save.source_unavailable"
        )
    finally:
        controller.shutdown()


def test_workspace_track_deletion_is_reviewed_saved_and_cleared(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    removed = workspace.tracks[0].track_id
    workspace.remove_tracks((removed,), workspace.edit_revision)
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.request is not None and controller.request.delete_omissions
        assert controller.request.discard_removed_track_media
        assert controller.can_save, controller.review
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        assert not workspace.dirty and not workspace.delete_omissions
        assert removed not in {t.track_id for t in workspace.tracks}
        assert IPodLibrary(database.read_bytes()).snapshot == workspace.snapshot
    finally:
        controller.shutdown()


@pytest.mark.parametrize("automatic", [False, True])
def test_workspace_track_deletion_permanently_removes_media(
    tmp_path: Path, automatic: bool
) -> None:
    device = build_device(tmp_path)
    settings = (
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
        if automatic
        else manual_settings()
    )
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    removed = workspace.tracks[0]
    media = device.root / removed.metadata.location
    workspace.remove_tracks((removed.track_id,), workspace.edit_revision)
    controller = LibraryWriteController(
        device.coordinator, workspace, devices, settings
    )
    try:
        if not automatic:
            controller.prepare()
            wait_for(lambda: controller.state is PreparationState.READY)
            controller.save()
        wait_for(lambda: controller.state is PreparationState.SAVED)
        assert controller.request is not None
        assert controller.request.discard_removed_track_media
        assert not media.exists()
        assert controller.save_result is not None
        assert controller.save_result.recovery_path == ""
    finally:
        controller.shutdown()
        devices.shutdown()


def test_workspace_playlist_removal_is_reviewed_saved_and_cleared(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    removed = workspace.playlists[0].playlist_id
    workspace.remove_playlist(removed, workspace.edit_revision)
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.request is not None and controller.request.delete_omissions
        assert controller.can_save, controller.review
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        assert not workspace.dirty and not workspace.delete_omissions
        assert removed not in {p.playlist_id for p in workspace.playlists}
        assert IPodLibrary(database.read_bytes()).snapshot == workspace.snapshot
    finally:
        controller.shutdown()


def test_new_folder_regular_and_smart_membership_are_saved_together(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    folder = workspace.create(PlaylistKind.FOLDER, "Trips")
    regular = workspace.create(PlaylistKind.PLAYLIST, "Train", folder.playlist_id)
    workspace.set_tracks(regular.playlist_id, (2, 1, 2))
    smart = workspace.create(
        PlaylistKind.SMART,
        "Twos",
        folder.playlist_id,
        smart=SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.TITLE, SmartOperator.IS, "Track 2"),)
            )
        ),
    )
    assert smart.track_ids == (2,)
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.can_save, controller.review
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        saved = {
            p.name: p
            for p in IPodLibrary.parse(database.read_bytes()).snapshot.playlists
        }
        assert saved["Train"].track_ids == (2, 1, 2)
        assert saved["Twos"].track_ids == (2,) and saved["Twos"].smart == smart.smart
        assert (
            saved["Train"].parent_id
            == saved["Twos"].parent_id
            == saved["Trips"].playlist_id
        )
        assert workspace.saved_playlist_ids is not None
        assert (
            workspace.saved_playlist_ids[folder.playlist_id]
            == saved["Trips"].playlist_id
        )
    finally:
        controller.shutdown()


class DelayedSaveService:
    def __init__(self, coordinator: DeviceCoordinator, *, after_save: bool) -> None:
        self.coordinator = coordinator
        self.after_save = after_save
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview:
        return self.coordinator.prepare_library(request, progress, cancelled)

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibrarySaveResult:
        if self.after_save:
            result = self.coordinator.save_library(
                review, expected, progress, cancelled
            )
            self.entered.set()
            self.release.wait(3)
            return result
        self.entered.set()
        self.release.wait(3)
        return self.coordinator.save_library(review, expected, progress, cancelled)


@pytest.mark.parametrize("after_save", (False, True))
def test_cancellation_and_stale_save_results_never_clear_newer_drafts(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    after_save: bool,
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    service = DelayedSaveService(coordinator, after_save=after_save)
    controller = LibraryWriteController(service, workspace, devices, manual_settings())
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        controller.save()
        wait_for(service.entered.is_set)
        if after_save:
            workspace.load(LibrarySnapshot())
        else:
            controller.cancel()
        service.release.set()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert not devices.busy and not workspace.locked
        if after_save:
            assert controller.state is PreparationState.STALE
            assert workspace.snapshot == LibrarySnapshot()
            assert database.read_bytes() != original
        else:
            assert controller.state is PreparationState.SAVE_FAILED
            assert workspace.dirty
            assert database.read_bytes() == original
            assert (
                controller.save_result
                and controller.save_result.issues[0].code == "save.cancelled"
            )
    finally:
        service.release.set()
        controller.shutdown()


def test_discovery_refresh_preserves_draft_and_prepared_review(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    devices.activeIPodChanged.connect(workspace.active_ipod_changed)
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        original_review = controller.review
        revision = workspace.revision
        active = devices.active_ipod
        assert active is not None
        refreshed = replace(
            active,
            candidate=replace(
                active.candidate, available_bytes=active.candidate.available_bytes - 1
            ),
        )
        devices.activeIPodChanged.emit(refreshed)
        assert workspace.dirty and workspace.revision == revision
        assert controller.review is original_review and controller.can_save
        # A freshly parsed source, even with identical values, is a new revision.
        reloaded = replace(active, library=replace(active.library))
        devices.activeIPodChanged.emit(reloaded)
        assert not workspace.dirty and controller.state is PreparationState.STALE
    finally:
        controller.shutdown()


def test_inspection_shows_captured_draft_stages_and_stale_output(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    dialog = LibraryReviewDialog(controller)
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.request is not None
        captured = controller.request
        report = json.loads(controller.inspection_json())
        assert report["version"] == 2
        assert report["resolution"]["effects"]["count"] > 0
        assert report["worker_measurements"]["items"][-1]["phase"] == "verification"
        assert report["request_is_current"] is True
        assert report["request"]["delete_omissions"] is False
        assert report["supplied_resources"]["pending_playback_sidecars"] is None
        assert report["target"]["signing_identity_supplied"] is True
        assert "firewire_guid" not in report["target"]
        assert "000a270012345678" not in controller.inspection_json().lower()
        assert report["changes"]["items"][0]["fields"] == [
            {
                "field": "name",
                "before": "Playlist",
                "desired": "Reviewed",
                "resolved": "Reviewed",
                "prepared": "Reviewed",
            }
        ]
        phases = [event.phase for event in controller.trace]
        assert phases[0] == "application.preparing"
        assert phases[-1] == "application.ready"
        assert (
            phases.index("database.serialization")
            < phases.index("database.signing")
            < phases.index("database.verification")
        )
        assert report["prepared"]["itunes"]["size"] > 0
        tree = dialog.findChild(QTreeWidget, "libraryReviewItems")
        assert tree is not None
        group = tree.topLevelItem(0)
        assert group is not None
        item = group.child(0)
        assert item is not None
        tree.setCurrentItem(item)
        details = dialog.findChild(QPlainTextEdit, "libraryReviewDetails")
        assert details is not None and '"before": "Playlist"' in details.toPlainText()
        workspace.rename(10, "Newer edit")
        stale = json.loads(controller.inspection_json())
        assert stale["state"] == "stale" and not stale["request_is_current"]
        assert stale["prepared"] == report["prepared"]
        assert controller.review is None and not controller.can_save
        assert captured.snapshot.playlists[0].name == "Reviewed"
        assert database.read_bytes() == original and workspace.dirty
    finally:
        dialog.deleteLater()
        controller.shutdown()


def test_inspection_exposes_generated_records_and_precise_requested_fields(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    active = devices.active_ipod
    assert active is not None
    original = database.read_bytes()
    desired = replace(
        active.library,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, podcast=t.track_id == 1))
            for t in active.library.tracks
        ),
    )
    request = LibraryPreparationRequest(
        desired, active, workspace.generation, workspace.revision
    )
    review = coordinator.prepare_library(request, lambda _: None, threading.Event())
    assert review.result.prepared is not None, review.result.issues
    report = json.loads(inspect_library_write(request, review, state="ready"))
    field = report["changes"]["items"][0]["fields"][0]
    assert field == {
        "field": "metadata.podcast",
        "before": False,
        "desired": True,
        "resolved": True,
        "prepared": True,
    }
    generated = report["resolution"]["generated_changes"]["items"]
    assert generated[0]["action"] == "add" and generated[0]["name"] == "Podcasts"
    name = next(f for f in generated[0]["fields"] if f["field"] == "name")
    assert name["before"] is None and name["desired"] is None
    assert name["resolved"] == name["prepared"] == "Podcasts"
    assert generated[0]["output_id"] > 0
    assert report["resolution"]["counts"]["playlists"] == len(desired.playlists) + 1
    assert database.read_bytes() == original


def test_inspection_bounds_large_membership_and_preserves_occurrences(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    workspace.set_tracks(10, (1, 2, 1) * 1000)
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    try:
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.request is not None and controller.review is not None
        report = json.loads(
            inspect_library_write(
                controller.request,
                controller.review,
                state=controller.state,
                limits=InspectionLimits(max_sequence_items=4),
            )
        )
        assert report["truncated"] is True
        entries = next(
            row
            for row in report["changes"]["items"][0]["fields"]
            if row["field"] == "entries"
        )
        assert entries["desired"]["count"] == 3000
        assert entries["desired"]["omitted"] == 2996
        occurrences = entries["desired"]["items"]
        assert [e["track_id"] for e in occurrences] == [1, 2, 1, 1]
        assert len({e["entry_id"] for e in occurrences}) == 4
        assert len(controller.request.snapshot.playlists[0].entries) == 3000
    finally:
        controller.shutdown()


def test_developer_report_dialog_opens_without_preparing_or_saving(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    original = database.read_bytes()
    controller = LibraryWriteController(
        coordinator, workspace, devices, manual_settings()
    )
    review = LibraryReviewDialog(controller)
    captured: list[str] = []

    def inspect_open_dialog() -> None:
        dialog = review.findChild(QDialog, "libraryWriteInspection")
        if dialog is not None:
            text = dialog.findChild(QPlainTextEdit, "libraryWriteInspectionJson")
            if text is not None:
                captured.append(text.toPlainText())
            dialog.reject()

    try:
        button = review.findChild(QPushButton, "inspectLibraryWrite")
        assert button is not None
        QTimer.singleShot(0, inspect_open_dialog)
        button.click()
        assert captured and json.loads(captured[0])["state"] == "idle"
        assert controller.request is None and controller.review is None
        assert workspace.dirty and database.read_bytes() == original
    finally:
        review.deleteLater()
        controller.shutdown()


def test_application_request_can_explicitly_authorize_omissions(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    active = devices.active_ipod
    assert active is not None
    original = database.read_bytes()
    request = LibraryPreparationRequest(
        replace(workspace.desired_snapshot(), playlists=()),
        active,
        workspace.generation,
        workspace.revision,
        delete_omissions=True,
    )
    review = coordinator.prepare_library(
        request, lambda _progress: None, threading.Event()
    )
    assert review.plan is not None and review.plan.draft.delete_omissions
    assert review.result.prepared is not None, review.result.issues
    assert review.result.prepared.snapshot.playlists == ()
    assert database.read_bytes() == original and workspace.dirty


def test_reviewed_photo_draft_is_saved_and_adopted(tmp_path: Path) -> None:
    root = tmp_path / "photo-ipod"
    metadata = root / "iPod_Control" / "Device"
    metadata.mkdir(parents=True)
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    database.parent.mkdir()
    database.write_bytes(library().serialize().itunes)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nFirewireGuid: 000A270012345678\n",
        encoding="utf-8",
    )
    photos_path = root / "Photos" / "Photo Database"
    photos_path.parent.mkdir()
    fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "PhotosDB"
        / "original-photo-library.b64"
    )
    photos_path.write_bytes(
        base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert active.library.photos is not None
    albums = active.library.photos.albums
    desired = replace(
        active.library,
        photos=replace(
            active.library.photos,
            albums=(albums[0], replace(albums[1], name="Sunsets")),
        ),
    )
    request = LibraryPreparationRequest(desired, active, 1, 1)

    review = coordinator.prepare_library(
        request,
        lambda _progress: None,
        threading.Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    report = json.loads(inspect_library_write(request, review, state="ready"))
    assert report["request"]["source_photos_fingerprint"] is not None
    assert report["request"]["desired_counts"]["photo_albums"] == 2
    photo_change = next(
        item for item in report["changes"]["items"] if item["subject"] == "photo_album"
    )
    assert photo_change["fields"] == [
        {
            "field": "name",
            "before": "Favorites",
            "desired": "Sunsets",
            "resolved": "Sunsets",
            "prepared": "Sunsets",
        }
    ]
    assert report["prepared"]["photos"]["size"] > 0
    assert tuple((change.path, change.action) for change in review.file_changes) == (
        ("Photos/Photo Database", "write"),
    )
    original_photos = photos_path.read_bytes()
    photos_path.write_bytes(original_photos + b"external change")
    stale_save = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        threading.Event(),
    )
    assert stale_save.active is None
    assert stale_save.issues[0].code == "save.source_unavailable"
    photos_path.write_bytes(original_photos)
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert active.library.photos is not None
    albums = active.library.photos.albums
    desired = replace(
        active.library,
        photos=replace(
            active.library.photos,
            albums=(albums[0], replace(albums[1], name="Sunsets")),
        ),
    )
    request = LibraryPreparationRequest(desired, active, 1, 1)
    review = coordinator.prepare_library(
        request,
        lambda _progress: None,
        threading.Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    result = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        threading.Event(),
    )

    assert result.active is not None, result.issues
    assert result.active.library.photos is not None
    assert result.active.library.photos.albums[1].name == "Sunsets"
    reparsed = IPodLibrary.parse(database.read_bytes()).with_photos(
        photos_path.read_bytes()
    )
    assert reparsed.snapshot == result.active.library
    coordinator.close()


def test_source_recheck_failure_retains_analysis_for_inspection(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    active = devices.active_ipod
    assert active is not None
    request = LibraryPreparationRequest(
        workspace.desired_snapshot(), active, workspace.generation, workspace.revision
    )

    def change_source(progress: WriteProgress) -> None:
        if progress.phase == "source.recheck":
            database.write_bytes(database.read_bytes() + b"external change")

    review = coordinator.prepare_library(request, change_source, threading.Event())
    assert review.plan is not None and review.resources is not None
    assert review.result.prepared is None
    assert review.result.issues[-1].code == "source.unavailable"
    report = json.loads(inspect_library_write(request, review, state="blocked"))
    assert report["changes"]["items"][0]["fields"][0]["desired"] == "Reviewed"
    assert report["prepared"] is None
    assert workspace.dirty


def test_default_mode_saves_each_edit_and_adopts_verified_output(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    track_model: TrackTableModel,
) -> None:
    coordinator, devices, workspace, database = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    workspace.reset_changes()
    track_model.reset_tracks(workspace.tracks)
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    original = database.read_bytes()
    try:
        workspace.rename(10, "Automatic playlist")
        workspace.apply_track_edits(
            (
                TrackUpdate(
                    workspace.tracks[0].track_id, (TrackFieldEdit("rating", 80),)
                ),
            ),
            workspace.edit_revision,
        )
        wait_for(lambda: controller.state is PreparationState.SAVED)
        saved = IPodLibrary.parse(database.read_bytes()).snapshot
        assert saved == workspace.snapshot
        assert track_model.tracks == saved.tracks
        assert saved.playlists[0].name == "Automatic playlist"
        assert saved.tracks[0].rating == 80
        assert not workspace.dirty and not workspace.locked and not devices.busy
        assert controller.save_result is not None
        assert database.read_bytes() != original
        assert controller.save_result.recovery_path == ""
        assert not tuple(
            database.parents[2].glob(".iopenpod-recovery/*/transaction.json")
        )

        workspace.rename(10, "Automatic again")
        wait_for(lambda: not workspace.dirty)
        assert controller.state is PreparationState.SAVED
        assert (
            IPodLibrary.parse(database.read_bytes()).snapshot.playlists[0].name
            == "Automatic again"
        )
    finally:
        controller.shutdown()


@pytest.mark.parametrize("prepared", (False, True))
def test_turning_drafting_off_saves_pending_changes(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    prepared: bool,
) -> None:
    coordinator, devices, workspace, database = session
    settings = manual_settings()
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    original = database.read_bytes()
    try:
        APPLICATION.processEvents()
        assert controller.state is PreparationState.IDLE
        if prepared:
            controller.prepare()
            wait_for(lambda: controller.state is PreparationState.READY)
        assert database.read_bytes() == original and workspace.dirty
        settings.set_global(DRAFT_ALL_CHANGES, False)
        wait_for(lambda: controller.state is PreparationState.SAVED)
        assert (
            IPodLibrary.parse(database.read_bytes()).snapshot.playlists[0].name
            == "Reviewed"
        )
        assert not workspace.dirty
    finally:
        controller.shutdown()


@pytest.mark.parametrize("read_only", (False, True))
def test_automatic_save_waits_for_device_reservations(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    read_only: bool,
) -> None:
    coordinator, devices, workspace, database = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    if read_only:
        assert devices.begin_read_only_operation()
    else:
        assert devices.begin_exclusive_operation()
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    original = database.read_bytes()
    try:
        if read_only:
            wait_for(lambda: controller.state is PreparationState.READY)
        else:
            APPLICATION.processEvents()
            assert controller.state is PreparationState.IDLE
        assert database.read_bytes() == original and workspace.dirty
        if read_only:
            devices.finish_read_only_operation()
        else:
            devices.finish_exclusive_operation()
        wait_for(lambda: controller.state is PreparationState.SAVED)
        assert not workspace.dirty
    finally:
        devices.finish_read_only_operation()
        devices.finish_exclusive_operation()
        controller.shutdown()


@pytest.mark.parametrize("during_save", (False, True))
def test_automatic_failure_retains_draft_reports_once_and_does_not_retry(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    during_save: bool,
) -> None:
    coordinator, devices, workspace, database = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    assert devices.begin_read_only_operation()
    changed = database.read_bytes() + b"external change"
    if not during_save:
        database.write_bytes(changed)
    controller = LibraryWriteController(coordinator, workspace, devices, settings)
    failures = QSignalSpy(controller.automaticSaveFailed)
    try:
        if during_save:
            wait_for(lambda: controller.state is PreparationState.READY)
            database.write_bytes(changed)
        devices.finish_read_only_operation()
        wait_for(lambda: failures.count() == 1)
        assert controller.state is (
            PreparationState.SAVE_FAILED if during_save else PreparationState.BLOCKED
        )
        request = controller.request
        for _ in range(5):
            controller.changed.emit()
            APPLICATION.processEvents()
        assert controller.request is request
        assert failures.count() == 1
        assert workspace.dirty and not workspace.locked and not devices.busy
        assert database.read_bytes() == changed
    finally:
        devices.finish_read_only_operation()
        controller.shutdown()


class HeldPreparationService:
    def __init__(self, coordinator: DeviceCoordinator) -> None:
        self.coordinator = coordinator
        self.entered = threading.Event()
        self.release = threading.Event()
        self.requests: list[LibraryPreparationRequest] = []
        self.saved: list[LibraryReview] = []

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.entered.set()
            self.release.wait(3)
        return self.coordinator.prepare_library(request, progress, cancelled)

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibrarySaveResult:
        self.saved.append(review)
        return self.coordinator.save_library(review, expected, progress, cancelled)


@pytest.mark.parametrize("during_preparation", (False, True))
def test_enabling_drafting_stops_automatic_acceptance(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    during_preparation: bool,
) -> None:
    coordinator, devices, workspace, database = session
    service = HeldPreparationService(coordinator)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = LibraryWriteController(service, workspace, devices, settings)
    original = database.read_bytes()
    try:
        if during_preparation:
            wait_for(service.entered.is_set)
        settings.set_global(DRAFT_ALL_CHANGES, True)
        service.release.set()
        if during_preparation:
            wait_for(lambda: controller.state is PreparationState.READY)
        else:
            APPLICATION.processEvents()
            assert controller.state is PreparationState.IDLE
        assert service.saved == []
        assert database.read_bytes() == original and workspace.dirty
    finally:
        service.release.set()
        controller.shutdown()


def test_edits_during_automatic_preparation_only_save_latest_revision(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, database = session
    service = HeldPreparationService(coordinator)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = LibraryWriteController(service, workspace, devices, settings)
    try:
        wait_for(service.entered.is_set)
        workspace.rename(10, "Latest edit")
        service.release.set()
        wait_for(lambda: controller.state is PreparationState.SAVED)
        assert len(service.requests) == 2 and len(service.saved) == 1
        assert (
            IPodLibrary.parse(database.read_bytes()).snapshot.playlists[0].name
            == "Latest edit"
        )
        assert not workspace.dirty
    finally:
        service.release.set()
        controller.shutdown()


@pytest.mark.parametrize("action", ("cancel", "disconnect", "shutdown"))
def test_automatic_preparation_cannot_save_after_invalidation(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    action: str,
) -> None:
    coordinator, devices, workspace, database = session
    service = HeldPreparationService(coordinator)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = LibraryWriteController(service, workspace, devices, settings)
    original = database.read_bytes()
    try:
        wait_for(service.entered.is_set)
        if action == "cancel":
            controller.cancel()
        elif action == "disconnect":
            workspace.active_ipod_changed(None)
            devices.activeIPodChanged.emit(None)
        service.release.set()
        if action == "shutdown":
            controller.shutdown()
        finish_workers(controller)
        for _ in range(3):
            APPLICATION.processEvents()
        assert len(service.requests) == 1 and service.saved == []
        assert database.read_bytes() == original
    finally:
        service.release.set()
        controller.shutdown()
