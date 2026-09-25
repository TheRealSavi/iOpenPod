"""Card controls and box selection retain ownership of their mouse gestures."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QStackedWidget, QStyleOptionViewItem
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.selection_grouping import (
    SelectionGroupingProxyModel,
    SelectionGroupingRole,
)
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_plan import SyncPlan
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.selection_checkbox import library_card_checkbox_rect
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata


class _EmptyArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        return None


@pytest.fixture
def selection_grid() -> Iterator[tuple[AlbumGridView, ThemeManager]]:
    tracks = tuple(
        Track(
            row,
            f"Track {row}",
            "Artist",
            f"Album {row}",
            180_000,
            metadata=TrackMetadata(location=f"C:/Music/track-{row}.mp3"),
        )
        for row in range(1, 4)
    )
    library = HostMediaLibrary(
        LibrarySnapshot(tracks), (), (), HostMediaCacheStats(inspected=len(tracks))
    )
    selection = SyncSelection()
    selection.reset(library, SyncPlan(()))
    selection.set_tracks_checked((track.track_id for track in tracks), True)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    controller = ArtworkController(_EmptyArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    parent = QStackedWidget()
    browser = HostLibraryBrowser(
        settings, theme, provider, LibraryWorkspace(), parent, selection
    )
    try:
        browser.load(library)
        page = browser.page_widgets[PageId.ALBUMS]
        parent.addWidget(page)
        parent.resize(900, 700)
        parent.show()
        APPLICATION.processEvents()
        grid = page.findChild(AlbumGridView, "albumGrid")
        assert grid is not None
        grid.doItemsLayout()
        APPLICATION.processEvents()
        yield grid, theme
    finally:
        browser.shutdown()
        provider.shutdown()
        controller.shutdown()
        parent.close()
        theme.close()


def _control_point(grid: AlbumGridView, theme: ThemeManager, control: str) -> QPoint:
    index = grid.model().index(0 if control == "header" else 1, 0)
    if control == "header":
        assert index.data(SelectionGroupingRole.IS_HEADER)
        return grid.visualRect(index).center()
    option = QStyleOptionViewItem()
    option.initFrom(grid)
    option.font = grid.font()
    option.rect = grid.visualRect(index)
    point = library_card_checkbox_rect(option, theme.typography).center().toPoint()
    assert grid.indexAt(point) == index
    return point


def _mouse_event(
    grid: AlbumGridView,
    event_type: QEvent.Type,
    point: QPoint,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.ShiftModifier,
) -> None:
    event = QMouseEvent(
        event_type,
        QPointF(point),
        QPointF(grid.viewport().mapToGlobal(point)),
        Qt.MouseButton.NoButton
        if event_type is QEvent.Type.MouseMove
        else Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton
        if event_type is QEvent.Type.MouseButtonRelease
        else Qt.MouseButton.LeftButton,
        modifiers,
    )
    APPLICATION.sendEvent(grid.viewport(), event)


@pytest.mark.parametrize("control", ["checkbox", "header"])
@pytest.mark.parametrize("release_on_control", [False, True])
@pytest.mark.parametrize(
    "modifiers", [Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier]
)
def test_drag_from_control_does_not_start_box_selection(
    selection_grid: tuple[AlbumGridView, ThemeManager],
    control: str,
    release_on_control: bool,
    modifiers: Qt.KeyboardModifier,
) -> None:
    grid, theme = selection_grid
    start = _control_point(grid, theme, control)
    finish = grid.visualRect(grid.model().index(3, 0)).center()

    _mouse_event(grid, QEvent.Type.MouseButtonPress, start, modifiers)
    _mouse_event(grid, QEvent.Type.MouseMove, finish, modifiers)

    assert grid.state() is QAbstractItemView.State.NoState
    assert not grid.selectionModel().selectedIndexes()
    _mouse_event(
        grid,
        QEvent.Type.MouseButtonRelease,
        start if release_on_control else finish,
        modifiers,
    )
    assert grid.state() is QAbstractItemView.State.NoState
    assert not grid.selectionModel().selectedIndexes()


@pytest.mark.parametrize("control", ["checkbox", "header"])
@pytest.mark.parametrize("start_on_card", [False, True])
@pytest.mark.parametrize(
    "release_modifiers",
    [Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier],
)
def test_box_selection_finishes_over_control_without_activating_it(
    selection_grid: tuple[AlbumGridView, ThemeManager],
    control: str,
    start_on_card: bool,
    release_modifiers: Qt.KeyboardModifier,
) -> None:
    grid, theme = selection_grid
    start = QPoint(grid.viewport().width() - 2, grid.viewport().height() - 2)
    finish = _control_point(grid, theme, control)
    assert not grid.indexAt(start).isValid()
    if start_on_card:
        start = grid.visualRect(grid.model().index(1, 0)).center()

    _mouse_event(grid, QEvent.Type.MouseButtonPress, start)
    _mouse_event(grid, QEvent.Type.MouseMove, finish)
    assert grid.state() is QAbstractItemView.State.DragSelectingState
    selected = grid.selectionModel().selectedIndexes()
    assert selected

    _mouse_event(grid, QEvent.Type.MouseButtonRelease, finish, release_modifiers)

    assert grid.state() is QAbstractItemView.State.NoState
    assert grid.selectionModel().selectedIndexes() == selected
    assert grid.model().index(0, 0).data(SelectionGroupingRole.EXPANDED)
    assert all(
        grid.model().index(row, 0).data(Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Checked
        for row in range(1, 4)
    )

    # A finished box must not continue changing selection as the pointer moves.
    APPLICATION.sendEvent(
        grid.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(start),
            QPointF(grid.viewport().mapToGlobal(start)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert grid.state() is QAbstractItemView.State.NoState
    assert grid.selectionModel().selectedIndexes() == selected


@pytest.mark.parametrize("control", ["checkbox", "header"])
def test_control_drag_stays_blocked_when_the_model_resets(
    selection_grid: tuple[AlbumGridView, ThemeManager], control: str
) -> None:
    grid, theme = selection_grid
    start = _control_point(grid, theme, control)
    _mouse_event(grid, QEvent.Type.MouseButtonPress, start)

    model = grid.model()
    assert isinstance(model, SelectionGroupingProxyModel)
    model.set_grouping_enabled(False)
    grid.set_sectioned_layout(False)
    grid.doItemsLayout()
    finish = grid.visualRect(model.index(2, 0)).center()
    _mouse_event(grid, QEvent.Type.MouseMove, finish)
    assert grid.state() is QAbstractItemView.State.NoState
    assert not grid.selectionModel().selectedIndexes()
    _mouse_event(grid, QEvent.Type.MouseButtonRelease, finish)
    assert grid.state() is QAbstractItemView.State.NoState
    assert not grid.selectionModel().selectedIndexes()
