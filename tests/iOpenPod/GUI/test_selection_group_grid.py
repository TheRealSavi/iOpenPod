"""Selection grouping renders as full-width collapsible grid sections."""

import pytest
from PySide6.QtCore import QPoint, Qt, qInstallMessageHandler
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QLineEdit,
    QListView,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
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
from iOpenPod.GUI.delegates.selection_group_delegate import SelectionGroupDelegate
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.library_card import library_card_rect
from iOpenPod.GUI.presentation.selection_checkbox import library_card_checkbox_rect
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata


@pytest.mark.parametrize("view_type", [QListView, EqualizedGridView])
@pytest.mark.parametrize("action", ["focus", "tab", "return", "escape", "hide"])
def test_selection_view_events_do_not_treat_the_view_as_an_editor(
    view_type: type[QListView], action: str
) -> None:
    source = QStandardItemModel()
    item = QStandardItem("Album")
    item.setEditable(False)
    source.appendRow(item)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    parent = QWidget()
    layout = QVBoxLayout(parent)
    view = view_type(parent)
    view.setModel(source)
    delegate = SelectionGroupDelegate(QStyledItemDelegate(view), theme, view)
    view.setItemDelegate(delegate)
    commits = QSignalSpy(delegate.commitData)
    closes = QSignalSpy(delegate.closeEditor)
    search = QLineEdit(parent)
    layout.addWidget(view)
    layout.addWidget(search)
    messages: list[str] = []
    previous = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        parent.show()
        parent.activateWindow()
        view.setFocus()
        APPLICATION.processEvents()
        assert view.hasFocus()

        if action == "focus":
            search.setFocus()
        elif action == "hide":
            view.hide()
        else:
            key = {
                "tab": Qt.Key.Key_Tab,
                "return": Qt.Key.Key_Return,
                "escape": Qt.Key.Key_Escape,
            }[action]
            QTest.keyClick(view, key)
        APPLICATION.processEvents()
        if action in {"focus", "tab"}:
            assert search.hasFocus()
        assert not [
            message for message in messages if "does not belong to this view" in message
        ]
        assert commits.count() == 0
        assert closes.count() == 0
    finally:
        parent.close()
        theme.close()
        qInstallMessageHandler(previous)


def test_selection_delegate_preserves_real_editor_commit_and_close() -> None:
    source = QStandardItemModel()
    source.appendRow(QStandardItem("Before"))
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    view = QListView()
    view.setModel(source)
    delegate = SelectionGroupDelegate(QStyledItemDelegate(view), theme, view)
    view.setItemDelegate(delegate)
    commits = QSignalSpy(delegate.commitData)
    closes = QSignalSpy(delegate.closeEditor)
    try:
        view.show()
        view.activateWindow()
        APPLICATION.processEvents()
        index = source.index(0, 0)
        view.setCurrentIndex(index)
        view.edit(index)
        editor = view.findChild(QLineEdit)
        assert editor is not None
        editor.setText("After")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        APPLICATION.processEvents()

        assert index.data() == "After"
        assert commits.count() == 1
        assert closes.count() == 1
    finally:
        view.close()
        theme.close()


def test_group_headers_span_grid_and_toggle_from_the_disclosure_row() -> None:
    source = QStandardItemModel()
    for position in range(8):
        item = QStandardItem(f"Item {position}")
        item.setCheckable(True)
        item.setCheckState(
            Qt.CheckState.Checked
            if position < 3
            else Qt.CheckState.PartiallyChecked
            if position == 3
            else Qt.CheckState.Unchecked
        )
        source.appendRow(item)
    grouped = SelectionGroupingProxyModel(source)
    grouped.set_grouping_enabled(True)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    view = EqualizedGridView()
    view.setModel(grouped)
    view.setItemDelegate(SelectionGroupDelegate(QStyledItemDelegate(view), theme, view))
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setMovement(QListView.Movement.Static)
    view.setMouseTracking(True)
    view.viewport().setMouseTracking(True)
    view.set_sectioned_layout(True)

    try:
        view.resize(760, 520)
        view.show()
        APPLICATION.processEvents()
        view.doItemsLayout()
        APPLICATION.processEvents()

        header_indexes = tuple(
            grouped.index(row, 0)
            for row in range(grouped.rowCount())
            if grouped.index(row, 0).data(SelectionGroupingRole.IS_HEADER)
        )
        assert len(header_indexes) == 3
        first_header_rect = view.visualRect(header_indexes[0])
        first_item_rect = view.visualRect(grouped.index(1, 0))
        assert first_header_rect.height() == LAYOUT.control_height_large
        assert first_header_rect.width() >= view.viewport().width() - 16
        assert first_item_rect.top() >= first_header_rect.bottom()

        row_count = grouped.rowCount()
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            first_header_rect.center(),
        )
        APPLICATION.processEvents()

        assert grouped.rowCount() == row_count - 3
        assert grouped.index(0, 0).data(SelectionGroupingRole.EXPANDED) is False

        view.setCurrentIndex(grouped.index(0, 0))
        view.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(view, Qt.Key.Key_Space)
        APPLICATION.processEvents()

        assert grouped.rowCount() == row_count
        assert grouped.index(0, 0).data(SelectionGroupingRole.EXPANDED) is True
    finally:
        view.close()
        theme.close()


def test_host_sync_album_grouping_exposes_selected_mixed_and_deselected() -> None:
    tracks = (
        _track(1, "Selected", "C:/Music/selected.mp3"),
        _track(2, "Mixed", "C:/Music/mixed-selected.mp3"),
        _track(3, "Mixed", "C:/Music/mixed-deselected.mp3"),
        _track(4, "Deselected", "C:/Music/deselected.mp3"),
    )
    library = HostMediaLibrary(
        LibrarySnapshot(tracks),
        (),
        (),
        HostMediaCacheStats(inspected=len(tracks)),
    )
    selection = SyncSelection()
    selection.reset(library, SyncPlan(()))
    assert selection.set_tracks_checked((1, 2), True)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    device_controller = ArtworkController(_EmptyArtworkLoader())
    device_provider = ArtworkPixmapProvider(device_controller)
    parent = QStackedWidget()
    browser = HostLibraryBrowser(
        settings,
        theme,
        device_provider,
        LibraryWorkspace(),
        parent,
        selection,
    )

    try:
        browser.load(library)
        page = browser.page_widgets[PageId.ALBUMS]
        parent.addWidget(page)
        parent.resize(900, 700)
        parent.show()
        APPLICATION.processEvents()
        grouping = page.findChild(QToolButton, "selectionGrouping")
        grid = page.findChild(AlbumGridView, "albumGrid")
        assert grouping is not None and grid is not None

        assert grouping.isChecked()

        model = grid.model()
        assert isinstance(model, SelectionGroupingProxyModel)
        assert model.grouping_enabled
        assert tuple(
            model.index(row, 0).data()
            for row in range(model.rowCount())
            if model.index(row, 0).data(SelectionGroupingRole.IS_HEADER)
        ) == ("Selected", "Mixed", "Deselected")
        assert grid.sectioned_layout

        grouping.click()
        APPLICATION.processEvents()
        browser.retranslate()
        assert not grouping.isChecked()
        assert not model.grouping_enabled
        assert not grid.sectioned_layout
        assert model.rowCount() == 3
    finally:
        browser.shutdown()
        device_provider.shutdown()
        device_controller.shutdown()
        parent.close()
        theme.close()


def test_host_sync_album_card_click_and_checkbox_are_separate_actions() -> None:
    track = _track(1, "Album", "C:/Music/track.mp3")
    library = HostMediaLibrary(
        LibrarySnapshot((track,)),
        (),
        (),
        HostMediaCacheStats(inspected=1),
    )
    selection = SyncSelection()
    selection.reset(library, SyncPlan(()))
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    device_controller = ArtworkController(_EmptyArtworkLoader())
    device_provider = ArtworkPixmapProvider(device_controller)
    parent = QStackedWidget()
    browser = HostLibraryBrowser(
        settings,
        theme,
        device_provider,
        LibraryWorkspace(),
        parent,
        selection,
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

        model = grid.model()
        index = model.index(1, 0)
        card_rect = grid.visualRect(index)
        option = QStyleOptionViewItem()
        option.initFrom(grid)
        option.font = grid.font()
        option.rect = card_rect
        checkbox_point = (
            library_card_checkbox_rect(
                option,
                theme.typography,
            )
            .center()
            .toPoint()
        )
        rendered_card_rect = library_card_rect(option, theme.typography)
        card_point = (rendered_card_rect.bottomLeft() + QPoint(16, -16)).toPoint()
        assert grid.indexAt(card_point) == index

        assert not grid.currentIndex().isValid()
        assert index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked

        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            checkbox_point,
        )
        APPLICATION.processEvents()

        assert index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        assert not grid.currentIndex().isValid()

        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            card_point,
        )
        APPLICATION.processEvents()

        assert grid.currentIndex() == index
        assert index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    finally:
        browser.shutdown()
        device_provider.shutdown()
        device_controller.shutdown()
        parent.close()
        theme.close()


class _EmptyArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        return None


def _track(track_id: int, album: str, location: str) -> Track:
    return Track(
        track_id,
        f"Track {track_id}",
        "Artist",
        album,
        180_000,
        metadata=TrackMetadata(location=location),
    )
