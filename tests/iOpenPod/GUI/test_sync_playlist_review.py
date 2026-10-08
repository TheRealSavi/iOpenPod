"""Playlist-only changes remain explicit and executable from Sync Review."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox, QLabel, QPlainTextEdit, QPushButton
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
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
