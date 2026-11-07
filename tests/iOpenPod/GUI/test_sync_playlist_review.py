"""Playlist-only changes remain explicit and executable from Sync Review."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTableView
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.playlist_sync import PlaylistSyncChoice, PlaylistSyncReviewItem
from iOpenPod.app.sync_execution import (
    PlaylistSyncChange,
    SyncExecutionResult,
    SyncExecutionStatus,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.playlist_sync_review import (
    PlaylistMatchDialog,
    PlaylistSyncReview,
)
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind


def _row(change: PlaylistSyncChange, identity: int = 1) -> PlaylistSyncReviewItem:
    return PlaylistSyncReviewItem(
        identity, change.name, PlaylistSyncChoice(identity), change=change
    )


def _match_target_id(dialog: PlaylistMatchDialog) -> int | None:
    return dialog.target_id


@pytest.fixture
def workspace() -> Iterator[SyncWorkspace]:
    context = build_context()
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = SyncWorkspace(context.settings, context.theme_manager, artwork)
    page.resize(1050, 800)
    page.show()
    page.show_review()
    page.set_execution_available(True)
    try:
        yield page
    finally:
        page.shutdown()
        artwork.shutdown()
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        context.shutdown()


def test_workspace_labels_finished_execution_as_result(
    workspace: SyncWorkspace,
) -> None:
    workspace.show_execution()
    workspace.execution.show_result(SyncExecutionResult(SyncExecutionStatus.SUCCESS))
    labels = workspace.findChildren(QLabel, "syncStageIndicator")
    assert labels[-1].text() == "4  Result"
    workspace.execution.begin_recovery(cleanup=True)
    assert labels[-1].text() == "4  Sync"
    workspace.execution.show_result(SyncExecutionResult(SyncExecutionStatus.SUCCESS))
    assert labels[-1].text() == "4  Result"
    workspace.show_scan("Scanning again")
    assert labels[-1].text() == "4  Sync"


def test_playlist_only_changes_require_checked_option_and_executable_review(
    workspace: SyncWorkspace,
) -> None:
    execute = workspace.findChild(QPushButton, "executeSync")
    checkbox = workspace.findChild(QCheckBox, "reconcileSyncPlaylists")
    summary = workspace.findChild(QLabel, "syncReviewSummary")
    assert execute is not None and checkbox is not None and summary is not None
    changed = QSignalSpy(workspace.playlistReconciliationChanged)
    assert workspace.reconcile_playlists
    assert not execute.isEnabled()

    workspace.set_playlist_preview(
        (_row(PlaylistSyncChange("Favorites", "update", 0, 0, True)),)
    )
    assert execute.isEnabled()
    assert summary.text() == "0 of 0 selected · 1 Playlist change"
    checkbox.click()
    assert not workspace.reconcile_playlists
    assert not execute.isEnabled()
    assert changed.count() == 1
    assert summary.text().endswith("0 Playlist changes")
    checkbox.click()
    assert execute.isEnabled()
    workspace.set_execution_available(False)
    assert not execute.isEnabled()
    workspace.set_execution_available(True)
    workspace.show_selection()
    assert not execute.isEnabled()


@pytest.mark.parametrize("reset", ["clear", "scan"])
@pytest.mark.parametrize(
    ("artwork_pending", "photos_pending", "repair_label"),
    [
        (True, False, "Artwork repair"),
        (False, True, "Photo Database repair"),
    ],
    ids=["artwork", "photos"],
)
def test_pending_database_repair_is_visible_and_executable_without_media_changes(
    tmp_path: Path,
    workspace: SyncWorkspace,
    reset: str,
    artwork_pending: bool,
    photos_pending: bool,
    repair_label: str,
) -> None:
    device = build_device(tmp_path)
    try:
        workspace.load_comparison(
            HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
            SyncPlan(()),
            replace(
                device.active,
                artwork_repairs_pending=artwork_pending,
                photos_repairs_pending=photos_pending,
            ),
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        workspace.show_review()
        execute = workspace.findChild(QPushButton, "executeSync")
        summary = workspace.findChild(QLabel, "syncReviewSummary")
        assert execute is not None and summary is not None
        assert execute.isEnabled()
        assert repair_label in summary.text()
        if reset == "clear":
            workspace.clear()
        else:
            workspace.show_scan("Scanning")
        workspace.show_review()
        assert not execute.isEnabled()
        assert repair_label not in summary.text()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("reset", ["clear", "scan"])
@pytest.mark.parametrize("sqlite", [False, True])
def test_library_refresh_is_available_without_media_changes(
    tmp_path: Path, workspace: SyncWorkspace, reset: str, sqlite: bool
) -> None:
    device = build_device(tmp_path)
    try:
        profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(
            "MC688" if sqlite else "MB145"
        )
        assert profile is not None
        workspace.load_comparison(
            HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
            SyncPlan(()),
            replace(device.active, profile=profile),
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        workspace.show_review()
        execute = workspace.findChild(QPushButton, "executeSync")
        assert execute is not None
        assert execute.isEnabled()
        assert execute.text() == "Refresh Library"
        requested = QSignalSpy(workspace.executeRequested)
        execute.click()
        assert requested.count() == 1
        workspace.set_execution_available(False)
        assert not execute.isEnabled()
        workspace.set_execution_available(True)
        if reset == "clear":
            workspace.clear()
        else:
            workspace.show_scan("Scanning")
        workspace.show_review()
        assert not execute.isEnabled()
        assert execute.text() == "Sync Selected"
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    ("count", "label"), [(1, "1 Podcast will"), (2, "2 Podcasts will")]
)
def test_podcast_settings_are_disclosed_and_allow_sync_without_host_changes(
    workspace: SyncWorkspace,
    count: int,
    label: str,
) -> None:
    execute = workspace.findChild(QPushButton, "executeSync")
    detail = workspace.findChild(QLabel, "syncPodcastReviewDetail")
    assert execute is not None and detail is not None
    workspace.set_podcast_count(count)
    assert execute.isEnabled()
    assert label in detail.text() and "removed" in detail.text()
    assert not detail.isHidden()
    workspace.set_execution_available(False)
    assert not execute.isEnabled()
    workspace.set_execution_available(True)
    workspace.set_podcast_count(0)
    assert not execute.isEnabled() and detail.isHidden()


def test_dedicated_podcast_execution_has_its_own_title(
    workspace: SyncWorkspace,
) -> None:
    title = workspace.findChild(QLabel, "syncWorkspaceTitle")
    assert title is not None
    workspace.show_execution(podcasts=True)
    assert title.text() == "Sync Podcasts"
    workspace.show_scan("Scanning")
    assert title.text() == "Sync with Host"


def test_media_changes_can_sync_with_playlist_reconciliation_off(
    workspace: SyncWorkspace,
) -> None:
    removal = SyncPlanItem(
        SyncPlanAction.REMOVE,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.IPOD_ONLY,
        "Track",
        ipod_path="iPod_Control/Music/F00/track.m4a",
        ipod_id=123,
    )
    workspace.selection.reset(
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        SyncPlan((removal,)),
    )
    workspace.selection.set_removal_checked(removal, True)
    workspace.show_review()
    checkbox = workspace.findChild(QCheckBox, "reconcileSyncPlaylists")
    execute = workspace.findChild(QPushButton, "executeSync")
    assert checkbox is not None and execute is not None
    checkbox.click()
    assert not workspace.reconcile_playlists
    assert execute.isEnabled()


def test_playlist_preview_is_readable_literal_text_with_bounded_scrolling(
    workspace: SyncWorkspace,
) -> None:
    changes = (
        PlaylistSyncChange("<Favorites>", "create", 3, 0, False),
        PlaylistSyncChange("Road Trip", "update", 2, 1, True),
        *(
            PlaylistSyncChange(f"Playlist {i}", "update", 0, 1, False)
            for i in range(1000)
        ),
    )
    workspace.set_playlist_preview(
        tuple(_row(change, index) for index, change in enumerate(changes))
    )
    APPLICATION.processEvents()
    preview = workspace.findChild(QTableView, "syncPlaylistReviewChanges")
    assert preview is not None and preview.isVisible()
    assert preview.editTriggers() == QTableView.EditTrigger.NoEditTriggers
    assert preview.accessibleName() == "Playlist Sync choices"
    assert preview.model().index(0, 0).data() == "<Favorites>"
    assert preview.model().index(0, 2).data() == "Create · 3 added, 0 removed"
    assert preview.model().index(1, 2).data() == "2 added, 1 removed · Reorder"
    assert preview.height() <= 220
    assert preview.verticalScrollBar().maximum() > 0


@pytest.mark.parametrize("reset", ["clear", "scan"])
def test_new_scan_and_exit_clear_preview_and_restore_checked_default(
    workspace: SyncWorkspace, reset: str
) -> None:
    workspace.set_playlist_preview(
        (_row(PlaylistSyncChange("New", "create", 1, 0, False)),)
    )
    checkbox = workspace.findChild(QCheckBox, "reconcileSyncPlaylists")
    preview = workspace.findChild(QTableView, "syncPlaylistReviewChanges")
    execute = workspace.findChild(QPushButton, "executeSync")
    assert checkbox is not None and preview is not None and execute is not None
    checkbox.click()
    changed = QSignalSpy(workspace.playlistReconciliationChanged)
    if reset == "clear":
        workspace.clear()
    else:
        workspace.show_scan("Scanning")
    assert workspace.reconcile_playlists
    assert changed.count() == 0
    assert preview.model().rowCount() == 0
    assert not preview.isVisible()
    assert not execute.isEnabled()
    workspace.show_review()
    assert not execute.isEnabled()


def test_individual_playlist_choices_survive_preview_refresh_and_leave_media_alone(
    workspace: SyncWorkspace,
) -> None:
    rows = (
        _row(PlaylistSyncChange("A", "update", 0, 1, False), 1),
        _row(PlaylistSyncChange("B", "create", 2, 0, False), 2),
    )
    workspace.set_playlist_preview(rows)
    review = workspace.findChild(PlaylistSyncReview)
    execute = workspace.findChild(QPushButton, "executeSync")
    assert review is not None and execute is not None
    original = workspace.selection.selected_plan
    review.table.setCurrentIndex(review.model.index(0, 0))
    review.table.setFocus()
    from PySide6.QtTest import QTest

    QTest.keyClick(review.table, Qt.Key.Key_Space)
    assert workspace.playlist_choices == (PlaylistSyncChoice(1, included=False),)
    assert execute.isEnabled()
    assert workspace.selection.selected_plan == original
    workspace.set_playlist_preview(
        tuple(
            replace(row, choice=workspace.playlist_choices[0])
            if row.host_playlist_id == 1
            else row
            for row in rows
        )
    )
    assert (
        review.model.index(0, 0).data(Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Unchecked
    )
    review.model.setData(
        review.model.index(1, 0),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert not execute.isEnabled()
    assert workspace.selection.selected_plan == original


def test_skipped_reasons_are_visible_and_do_not_enable_sync(
    workspace: SyncWorkspace,
) -> None:
    row = PlaylistSyncReviewItem(
        1,
        "Road trip",
        PlaylistSyncChoice(1),
        issue_code="sync.playlist_incomplete",
        detail="Resolve missing source entries and rescan.",
    )
    workspace.set_playlist_preview((row,))
    execute = workspace.findChild(QPushButton, "executeSync")
    review = workspace.findChild(PlaylistSyncReview)
    assert execute is not None and review is not None
    assert not execute.isEnabled()
    assert review.model.index(0, 2).data() == "Needs attention"
    assert any(label.text() == row.detail for label in review.findChildren(QLabel))
    button = workspace.findChild(QPushButton, "changePlaylistMatch")
    assert button is not None and button.isEnabled()


@pytest.mark.parametrize("target_id", [10, 11919153248416957672, (1 << 64) - 1])
def test_match_dialog_preserves_initial_target_and_create_new_choice(
    workspace: SyncWorkspace, target_id: int
) -> None:
    row = replace(
        _row(PlaylistSyncChange("Host", "update", 0, 0, False)),
        target_id=target_id,
    )
    dialog = PlaylistMatchDialog(
        row, LibrarySnapshot(playlists=(Playlist(target_id, "Existing"),)), workspace
    )
    try:
        assert dialog.targets.currentRow() == 1
        assert _match_target_id(dialog) == target_id
        assert any(
            label.text() == "Empty Playlist" for label in dialog.findChildren(QLabel)
        )
        dialog.targets.setCurrentRow(0)
        assert _match_target_id(dialog) is None
        assert any(
            label.text() == "A new Playlist will be added to the iPod."
            for label in dialog.findChildren(QLabel)
        )
        dialog.targets.setCurrentRow(1)
        assert _match_target_id(dialog) == target_id
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("target_id", [10, 11919153248416957672, (1 << 64) - 1])
@pytest.mark.parametrize("accept", [False, True])
def test_match_dialog_only_applies_the_accepted_target(
    workspace: SyncWorkspace, accept: bool, target_id: int
) -> None:
    row = _row(PlaylistSyncChange("Host", "create", 0, 0, False))
    library = LibrarySnapshot(
        playlists=(
            Playlist(target_id, "Existing"),
            Playlist(20, "Managed", system_managed=True),
            Playlist(30, "Folder", kind=PlaylistKind.FOLDER),
        )
    )
    workspace.set_playlist_preview((row,), library)
    button = workspace.findChild(QPushButton, "changePlaylistMatch")
    assert button is not None

    def choose() -> None:
        dialog = APPLICATION.activeModalWidget()
        assert isinstance(dialog, PlaylistMatchDialog)
        assert dialog.targets.count() == 2  # Create new and the regular target.
        dialog.targets.setCurrentRow(1)
        assert dialog.target_id == target_id
        if accept:
            dialog.accept()
        else:
            dialog.reject()

    QTimer.singleShot(0, choose)
    button.click()
    assert workspace.playlist_choices == (
        (PlaylistSyncChoice(1, automatic=False, target_id=target_id),) if accept else ()
    )
