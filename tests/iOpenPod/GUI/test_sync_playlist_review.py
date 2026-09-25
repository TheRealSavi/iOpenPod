"""Playlist-only changes remain explicit and executable from Sync Review."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox, QLabel, QPlainTextEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.sync_execution import PlaylistSyncChange
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iPodDB.library import LibrarySnapshot


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
        (PlaylistSyncChange("Favorites", "update", 0, 0, True),)
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
    workspace.set_playlist_preview(changes)
    APPLICATION.processEvents()
    preview = workspace.findChild(QPlainTextEdit, "syncPlaylistReviewChanges")
    assert preview is not None and preview.isVisible()
    assert preview.isReadOnly()
    assert preview.accessibleName() == "Playlist changes"
    assert "Create <Favorites>: 3 added, 0 removed" in preview.toPlainText()
    assert (
        "Update Road Trip: 2 added, 1 removed, order changed" in preview.toPlainText()
    )
    assert preview.height() <= 150
    assert preview.verticalScrollBar().maximum() > 0


@pytest.mark.parametrize("reset", ["clear", "scan"])
def test_new_scan_and_exit_clear_preview_and_restore_checked_default(
    workspace: SyncWorkspace, reset: str
) -> None:
    workspace.set_playlist_preview((PlaylistSyncChange("New", "create", 1, 0, False),))
    checkbox = workspace.findChild(QCheckBox, "reconcileSyncPlaylists")
    preview = workspace.findChild(QPlainTextEdit, "syncPlaylistReviewChanges")
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
    assert preview.toPlainText() == ""
    assert preview.isHidden()
    assert not execute.isEnabled()
    workspace.show_review()
    assert not execute.isEnabled()
