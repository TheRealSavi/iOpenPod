"""Bulk Host selection actions update membership together and restore scan defaults."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    LibrarySnapshot,
    MediaType,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Track,
    TrackMetadata,
)


def _library() -> HostMediaLibrary:
    return HostMediaLibrary(
        LibrarySnapshot(
            tracks=(
                Track(
                    1,
                    "Song",
                    "Artist",
                    "Album",
                    1000,
                    metadata=TrackMetadata(location="C:/Music/song.mp3"),
                ),
                Track(
                    2,
                    "Movie",
                    "",
                    "",
                    1000,
                    media_types=(MediaType.VIDEO,),
                    metadata=TrackMetadata(location="C:/Movies/movie.mp4"),
                ),
            ),
            photos=PhotoLibrary(
                photos=(
                    Photo(
                        1,
                        representations=(
                            PhotoRepresentation(
                                PhotoRepresentationKind.FULL_RESOLUTION,
                                1,
                                "C:/Photos/photo.jpg",
                                0,
                                100,
                                10,
                                10,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        (),
        (),
        HostMediaCacheStats(),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[SyncWorkspace]:
    context = build_context()
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = SyncWorkspace(context.settings, context.theme_manager, artwork)
    device = build_device(tmp_path)
    page.resize(1050, 800)
    try:
        page.load_comparison(
            _library(),
            SyncPlan(()),
            device.active,
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        page.show()
        yield page
    finally:
        page.shutdown()
        artwork.shutdown()
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        context.shutdown()
        device.coordinator.close()


def _button(workspace: SyncWorkspace) -> QPushButton:
    button = workspace.findChild(QPushButton, "toggleAllSyncMedia")
    assert button is not None
    return button


def _comparison(*, all_matched: bool = False) -> SyncPlan:
    return SyncPlan(
        tuple(
            SyncPlanItem(
                SyncPlanAction.UNCHANGED if matched else SyncPlanAction.ADD,
                kind,
                SyncPlanBasis.CONTENT_MATCH if matched else SyncPlanBasis.HOST_ONLY,
                "Existing media" if matched else "New media",
                "",
                path,
                None,
                identity if matched else None,
            )
            for kind, path, identity, matched in (
                (SyncPlanMediaKind.TRACK, "C:/Music/song.mp3", 1, True),
                (SyncPlanMediaKind.TRACK, "C:/Movies/movie.mp4", 2, all_matched),
                (SyncPlanMediaKind.PHOTO, "C:/Photos/photo.jpg", 1, True),
            )
        )
    )


def test_toggle_includes_filtered_tracks_and_other_media_pages(
    workspace: SyncWorkspace,
) -> None:
    browser = workspace.browser
    assert browser is not None
    tracks = browser.page_widgets[PageId.TRACKS]
    toolbar = tracks.findChild(LibraryToolbar)
    table = tracks.findChild(TrackTable)
    assert toolbar is not None and table is not None
    toolbar.set_query("Song")
    toolbar.queryChanged.emit("Song")
    assert table.model().rowCount() == 1
    selection = workspace.selection
    selection.set_tracks_checked((1,), True)
    changed = QSignalSpy(selection.changed)
    host_changed = QSignalSpy(selection.hostSelectionChanged)
    assert workspace.findChild(QLabel, "syncSelectionSummary") is None
    button = _button(workspace)
    assert button.isEnabled()
    assert button.text() == "Select all media"

    button.click()

    assert changed.count() == host_changed.count() == 1
    assert selection.selected_host_count == 3
    assert selection.track_check_state(2) is Qt.CheckState.Checked
    assert selection.photo_check_state(1) is Qt.CheckState.Checked
    assert button.text() == "Deselect all media"

    button.click()

    assert changed.count() == host_changed.count() == 2
    assert selection.selected_host_count == 0
    assert button.text() == "Select all media"
    assert table.model().rowCount() == 1


def test_toggle_tracks_initial_and_individual_selections(
    workspace: SyncWorkspace,
) -> None:
    library = _library()
    comparison = _comparison(all_matched=True)
    selection = workspace.selection
    selection.reset(library, comparison)
    button = _button(workspace)
    assert button.text() == "Deselect all media"
    selection.set_photos_checked((1,), False)
    assert button.text() == "Select all media"
    selection.set_photos_checked((1,), True)
    assert button.text() == "Deselect all media"
    selection.set_tracks_checked((2,), False)
    assert button.text() == "Select all media"
    workspace.retranslate_ui()
    assert button.text() == "Select all media"
    selection.set_tracks_checked((2,), True)
    workspace.retranslate_ui()
    assert button.text() == "Deselect all media"
    assert selection.comparison is comparison

    workspace.clear()
    assert button.text() == "Select all media"
    assert not button.isEnabled()


@pytest.mark.parametrize("selection_mode", ["all", "none", "different"])
def test_revert_restores_initial_track_and_photo_membership(
    workspace: SyncWorkspace,
    selection_mode: str,
) -> None:
    selection = workspace.selection
    comparison = _comparison()
    selection.reset(_library(), comparison)
    revert = workspace.findChild(QPushButton, "revertSyncSelections")
    assert revert is not None
    assert revert.text() == "Revert selections"
    assert not revert.isEnabled()

    selection.set_all_host_media_checked(selection_mode == "all")
    if selection_mode == "different":
        selection.set_tracks_checked((1, 2), True)
        assert selection.selected_host_count == 2
    assert revert.isEnabled()
    changed = QSignalSpy(selection.changed)
    host_changed = QSignalSpy(selection.hostSelectionChanged)

    revert.click()

    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert selection.track_check_state(2) is Qt.CheckState.Unchecked
    assert selection.photo_check_state(1) is Qt.CheckState.Checked
    assert selection.selected_host_count == 2
    assert changed.count() == host_changed.count() == 1
    assert selection.comparison is comparison
    assert _button(workspace).text() == "Select all media"
    assert not revert.isEnabled()
    assert not selection.revert_host_media_selection()
    assert changed.count() == host_changed.count() == 1


def test_revert_uses_the_latest_scan_and_clears_its_baseline(
    workspace: SyncWorkspace,
) -> None:
    selection = workspace.selection
    selection.reset(_library(), _comparison())
    selection.set_all_host_media_checked(True)
    selection.reset(_library(), _comparison(all_matched=True))
    revert = workspace.findChild(QPushButton, "revertSyncSelections")
    assert revert is not None and not revert.isEnabled()
    selection.set_all_host_media_checked(False)
    revert.click()
    assert selection.selected_host_count == 3
    assert _button(workspace).text() == "Deselect all media"
    workspace.clear()
    assert not revert.isEnabled()
    assert not selection.revert_host_media_selection()
    assert selection.selected_host_count == 0


@pytest.mark.parametrize("missing_path", [False, True])
def test_toggle_disabled_without_selectable_media(
    workspace: SyncWorkspace,
    missing_path: bool,
) -> None:
    library = replace(
        _library(),
        snapshot=LibrarySnapshot(
            tracks=(Track(1, "Unavailable", "", "", 1000),) if missing_path else (),
        ),
    )
    workspace.selection.reset(library, SyncPlan(()))
    button = _button(workspace)
    assert button.text() == "Select all media"
    assert not button.isEnabled()
    changes = QSignalSpy(workspace.selection.changed)
    assert not workspace.selection.set_all_host_media_checked(True)
    assert changes.count() == 0


def test_toggle_stays_below_scrolling_navigation(workspace: SyncWorkspace) -> None:
    scroll = workspace.findChild(QScrollArea, "syncLibraryNavigationScroll")
    button = _button(workspace)
    navigation = button.parentWidget()
    assert navigation is not None
    navigation.setFixedHeight(240)
    APPLICATION.processEvents()
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    position = button.pos()
    assert button.geometry().top() > scroll.geometry().bottom()
    assert button.isVisible()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    APPLICATION.processEvents()
    assert button.pos() == position
    assert button.isVisible()
