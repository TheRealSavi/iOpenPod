"""Movies choose grid or the existing table independently of collection layouts."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QStackedWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.track_page import TrackPage
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.icon_segmented_control import IconSegmentedControl
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iOpenPod.GUI.widgets.track_grid import TrackGridView
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, MediaType, Track


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    tracks = (
        Track(
            1,
            "First Movie",
            "Director",
            "Collection",
            5_400_000,
            media_types=(MediaType.VIDEO,),
        ),
        Track(
            2,
            "Second Movie",
            "Director",
            "Collection",
            6_000_000,
            media_types=(MediaType.VIDEO,),
        ),
        Track(3, "Song", "Artist", "Album", 1000),
    )
    context.library_workspace.load(LibrarySnapshot(tracks))
    context.track_model.reset_tracks(tracks)
    yield context
    context.shutdown()


def _open_movies(
    context: AppContext,
) -> tuple[MainWindow, TrackPage, TrackGridView, TrackTable]:
    window = MainWindow(context, auto_discover=False)
    window.resize(1280, 850)
    window.show()
    bar = window.findChild(CompactTopBar)
    page = window.findChild(TrackPage, "moviesPage")
    assert bar is not None and page is not None
    bar.pageRequested.emit(PageId.MOVIES.value)
    APPLICATION.processEvents()
    grid = page.findChild(TrackGridView)
    table = page.findChild(TrackTable)
    assert grid is not None and table is not None
    return window, page, grid, table


@pytest.mark.parametrize("mode", list(IPodLibraryViewMode))
def test_movies_default_to_grid_and_single_click_only_selects(
    context: AppContext, mode: IPodLibraryViewMode
) -> None:
    context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
    window, page, grid, table = _open_movies(context)
    try:
        switch = page.findChild(IconSegmentedControl, "moviesViewModes")
        assert switch is not None and switch.isVisible()
        assert grid.isVisible() and not table.isVisible()
        assert grid.model() is table.model()
        assert grid.model().rowCount() == 2
        activated = QSignalSpy(page.trackActivated)
        index = grid.model().index(0, grid.modelColumn())
        QTest.mouseMove(grid.viewport(), grid.visualRect(index).center())
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        APPLICATION.processEvents()
        assert grid.currentIndex().data(TrackRole.TRACK_ID) == 1
        assert activated.count() == 0
        assert context.playback_controller.current_track is None
        assert grid.isVisible() and not table.isVisible()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None and pages.currentWidget() is page
        for setting in IPodLibraryViewMode:
            context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, setting.value)
            assert grid.isVisible() and not table.isVisible()
            assert grid.currentIndex() == index
    finally:
        window.close()
        window.deleteLater()


def test_movie_toggle_retains_existing_table_selection_sort_and_search(
    context: AppContext,
) -> None:
    window, page, grid, table = _open_movies(context)
    try:
        buttons = page.findChildren(IconButton)
        list_button = next(
            button for button in buttons if button.accessibleName() == "List view"
        )
        grid_button = next(
            button for button in buttons if button.accessibleName() == "Grid view"
        )
        actions = window.findChild(TrackActions)
        assert actions is not None
        grid.setCurrentIndex(grid.model().index(0, grid.modelColumn()))
        grid.selectionModel().select(
            grid.model().index(1, grid.modelColumn()),
            QItemSelectionModel.SelectionFlag.Select,
        )
        list_button.click()
        assert table.isVisible() and not grid.isVisible()
        assert table.property("tableId") == "movies"
        assert [track.track_id for track in actions.selection(table).tracks] == [1, 2]
        table.setColumnWidth(TrackColumn.TITLE, 333)
        table.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
        toolbar = page.findChild(LibraryToolbar)
        assert toolbar is not None
        toolbar.queryChanged.emit("Second")
        assert table.model().rowCount() == 1
        grid_button.click()
        assert grid.isVisible() and grid.model().rowCount() == 1
        assert grid.model().index(0, grid.modelColumn()).data(TrackRole.TRACK_ID) == 2
        assert [track.track_id for track in actions.selection(grid).tracks] == [2]
        list_button.click()
        assert table.columnWidth(TrackColumn.TITLE) == 333
        assert (
            table.horizontalHeader().sortIndicatorOrder()
            == Qt.SortOrder.DescendingOrder
        )
        for setting in IPodLibraryViewMode:
            context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, setting.value)
            assert table.isVisible() and not grid.isVisible()
        assert len(window.findChildren(TrackGridView)) == 1
    finally:
        window.close()
        window.deleteLater()


def test_movie_grid_keeps_explicit_track_actions(context: AppContext) -> None:
    context.settings.set_global(
        LIBRARY_DOUBLE_CLICK_SHORTCUT, LibraryDoubleClickShortcut.PLAY_NOW.value
    )
    window, _page, grid, _table = _open_movies(context)
    try:
        index = grid.model().index(0, grid.modelColumn())
        QTest.mouseMove(grid.viewport(), grid.visualRect(index).center())
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        assert context.playback_controller.current_track is None
        QTest.mouseDClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        assert (
            context.playback_controller.current_track
            == context.library_workspace.track(1)
        )
        grid.setCurrentIndex(grid.model().index(1, grid.modelColumn()))
        QTest.keyClick(grid, Qt.Key.Key_Return)
        assert (
            context.playback_controller.current_track
            == context.library_workspace.track(2)
        )
    finally:
        window.close()
        window.deleteLater()
