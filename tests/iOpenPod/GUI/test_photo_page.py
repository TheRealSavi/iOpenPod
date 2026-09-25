"""Public widget behavior for the three-pane Photo browser."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QPoint,
    QPointF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)

from iOpenPod.app.models.library_drag import PhotoSelectionMimeData
from iOpenPod.app.models.photo_album_membership_model import (
    PhotoAlbumMembershipRole,
)
from iOpenPod.app.models.photo_list_model import (
    PhotoAlbumRole,
    PhotoFilterProxyModel,
    PhotoRole,
    PhotoSortMode,
)
from iOpenPod.app.models.photos import FULL_RESOLUTION_REQUEST_ID
from iOpenPod.GUI.delegates.photo_album_membership_delegate import (
    photo_album_checkbox_rect,
)
from iOpenPod.GUI.dialogs.photo_album_editor import PhotoAlbumEditorDialog
from iOpenPod.GUI.dialogs.photo_album_manager import PhotoAlbumManagerDialog
from iOpenPod.GUI.dialogs.photo_metadata_editor import PhotoMetadataEditorDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.presentation.library_card import library_card_rect
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView
from iOpenPod.GUI.widgets.photo_album_membership_grid import (
    PhotoAlbumMembershipGrid,
)
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.photo_inspector import PhotoInspector
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoFileFormat,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from iOpenPod.app.context import AppContext


def _thumbnail(
    format_id: int,
    width: int,
    height: int,
    *,
    offset: int,
) -> PhotoRepresentation:
    return PhotoRepresentation(
        kind=PhotoRepresentationKind.THUMBNAIL,
        format_id=format_id,
        relative_path=f"Photos/Thumbs/F{format_id}_1.ithmb",
        offset=offset,
        size_bytes=width * height * 2,
        width=width,
        height=height,
    )


_SMALL = _thumbnail(901, 160, 120, offset=0)
_LARGE = _thumbnail(902, 640, 480, offset=61_440)
_FULL_RESOLUTION = PhotoRepresentation(
    kind=PhotoRepresentationKind.FULL_RESOLUTION,
    # Original iOpenPod writes MHNI format ID 1 for this representation.
    format_id=1,
    relative_path="Photos/Full Resolution/2026/IMG_0003.JPG",
    offset=0,
    size_bytes=3_200_000,
    width=4_032,
    height=3_024,
)
_PHOTOS = PhotoLibrary(
    photos=(
        Photo(
            photo_id=1,
            rating=40,
            original_date=1_700_000_001,
            taken_date=1_700_000_002,
            source_size_bytes=1_200_000,
            representations=(_SMALL,),
        ),
        Photo(
            photo_id=2,
            rating=60,
            original_date=1_700_000_003,
            taken_date=1_700_000_004,
            source_size_bytes=2_200_000,
            representations=(_LARGE,),
        ),
        Photo(
            photo_id=3,
            rating=80,
            original_date=1_700_000_005,
            taken_date=1_700_000_006,
            source_size_bytes=3_200_000,
            # Deliberately store the smaller copy first. The inspector presents
            # selectable device formats by descending rendered area.
            representations=(_SMALL, _FULL_RESOLUTION, _LARGE),
        ),
    ),
    albums=(
        PhotoAlbum(
            album_id=10,
            name="Photo Library",
            photo_ids=(1, 2, 3),
            kind=PhotoAlbumKind.MASTER,
        ),
        PhotoAlbum(
            album_id=20,
            name="Road trip",
            photo_ids=(3, 1),
        ),
        PhotoAlbum(album_id=30, name="Empty album"),
    ),
    formats=(
        PhotoFileFormat(901, _SMALL.size_bytes, _SMALL.relative_path),
        PhotoFileFormat(902, _LARGE.size_bytes, _LARGE.relative_path),
    ),
)


@dataclass(frozen=True, slots=True)
class _Browser:
    context: AppContext
    window: MainWindow
    page: PhotoPage


@pytest.fixture
def browser() -> Iterator[_Browser]:
    context = build_context()
    context.library_workspace.load(
        LibrarySnapshot(photos=_PHOTOS),
        photo_album_creation_type=2,
    )
    window = MainWindow(context, auto_discover=False)
    window.show()
    APPLICATION.processEvents()

    page = window.findChild(PhotoPage, "photosPage")
    assert page is not None
    yield _Browser(context, window, page)

    window.close()
    context.shutdown()
    window.deleteLater()
    APPLICATION.processEvents()


def _photo_ids(grid: PhotoGridView) -> tuple[int, ...]:
    model = grid.model()
    return tuple(
        int(model.index(row, 0).data(PhotoRole.ID)) for row in range(model.rowCount())
    )


def _metadata_section(
    metadata: QTreeWidget,
    title: str,
) -> dict[str, str]:
    section = next(
        (item for item in _top_level_items(metadata) if item.text(0) == title),
        None,
    )
    assert section is not None
    rows: dict[str, str] = {}
    for index in range(section.childCount()):
        child = section.child(index)
        assert child is not None
        rows[child.text(0)] = child.text(1)
    return rows


def _top_level_items(metadata: QTreeWidget) -> tuple[QTreeWidgetItem, ...]:
    items: list[QTreeWidgetItem] = []
    for index in range(metadata.topLevelItemCount()):
        item = metadata.topLevelItem(index)
        assert item is not None
        items.append(item)
    return tuple(items)


def test_photos_route_is_a_three_pane_grid_browser(browser: _Browser) -> None:
    pages = browser.window.findChild(QStackedWidget, "pageStack")
    photo_button = next(
        button
        for button in browser.window.findChildren(QPushButton)
        if button.property("pageId") == PageId.PHOTOS.value
    )

    photo_button.click()
    APPLICATION.processEvents()

    splitter = browser.page.findChild(QSplitter, "photoBrowserSplitter")
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    header = browser.page.findChild(PageHeader, "photosToolbar")
    source_list = browser.page.findChild(SourceListPanel, "photoAlbumPanel")
    assert pages is not None and pages.currentWidget() is browser.page
    assert header is not None and header.height() == LAYOUT.page_header_height
    assert source_list is not None
    assert source_list.title_label.text() == "PHOTO ALBUMS"
    assert source_list.count_label.text() == "2"
    assert source_list.minimumWidth() == LAYOUT.photo_album_pane_minimum_width
    assert splitter is not None and splitter.orientation() is Qt.Orientation.Horizontal
    assert splitter.count() == 3
    assert splitter.handleWidth() == LAYOUT.source_list_splitter_handle_width <= 4
    assert not splitter.childrenCollapsible()
    assert all(not splitter.isCollapsible(index) for index in range(splitter.count()))
    original_album_width = splitter.sizes()[0]
    splitter.moveSplitter(original_album_width + 40, 1)
    APPLICATION.processEvents()
    assert splitter.sizes()[0] > original_album_width
    assert isinstance(grid, EqualizedGridView)
    assert browser.page.findChild(TrackTable) is None


def test_album_source_list_filters_grid_in_membership_order(
    browser: _Browser,
) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    assert albums is not None and grid is not None
    album_model = albums.model()

    assert album_model.rowCount() == 3
    assert album_model.index(0, 0).data(PhotoAlbumRole.IS_ALL_PHOTOS) is True
    assert album_model.index(0, 0).data(PhotoAlbumRole.ID) is None
    assert album_model.index(0, 0).data() == "All Photos"
    assert tuple(
        album_model.index(row, 0).data() for row in range(album_model.rowCount())
    ) == ("All Photos", "Road trip", "Empty album")
    assert _photo_ids(grid) == (1, 2, 3)

    albums.setCurrentIndex(album_model.index(1, 0))
    APPLICATION.processEvents()

    assert _photo_ids(grid) == (3, 1)

    albums.setCurrentIndex(album_model.index(0, 0))
    APPLICATION.processEvents()
    assert _photo_ids(grid) == (1, 2, 3)


@pytest.mark.parametrize(
    ("source_album_row", "selected_rows", "expected_ids"),
    [(0, (0,), (3,)), (0, (0, 1), (3, 2)), (1, (0, 1), (3, 1))],
)
def test_photo_grid_drag_adds_selection_to_sidebar_album(
    browser: _Browser,
    monkeypatch: pytest.MonkeyPatch,
    source_album_row: int,
    selected_rows: tuple[int, ...],
    expected_ids: tuple[int, ...],
) -> None:
    pages = browser.window.findChild(QStackedWidget, "pageStack")
    albums = browser.page.findChild(QListView, "photoAlbumList")
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    assert pages is not None and albums is not None and grid is not None
    pages.setCurrentWidget(browser.page)
    albums.setCurrentIndex(albums.model().index(source_album_row, 0))
    model = grid.model()
    assert isinstance(model, PhotoFilterProxyModel)
    model.set_sort_mode(PhotoSortMode.RATING)
    grid.selectionModel().clearSelection()
    for row in selected_rows:
        grid.selectionModel().select(
            model.index(row, 0), QItemSelectionModel.SelectionFlag.Select
        )
    APPLICATION.processEvents()
    workspace = browser.context.library_workspace
    source_album = workspace.photo_album(20)
    source_snapshot = workspace.snapshot
    revision = workspace.edit_revision
    assert albums.dragDropMode() is QAbstractItemView.DragDropMode.DropOnly
    assert albums.showDropIndicator()

    def drop_into_sidebar(drag: QDrag, actions: Qt.DropAction) -> Qt.DropAction:
        data = drag.mimeData()
        assert isinstance(data, PhotoSelectionMimeData)
        assert data.photo_ids == expected_ids
        assert actions == Qt.DropAction.CopyAction
        position = albums.visualRect(albums.model().index(2, 0)).center()
        enter = QDragEnterEvent(
            position,
            actions,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(albums.viewport(), enter)
        assert enter.isAccepted()
        move = QDragMoveEvent(
            position,
            actions,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(albums.viewport(), move)
        assert move.isAccepted()
        drop = QDropEvent(
            QPointF(position),
            actions,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(albums.viewport(), drop)
        assert drop.isAccepted()
        return drop.dropAction()

    monkeypatch.setattr(QDrag, "exec", drop_into_sidebar)
    grid.startDrag(Qt.DropAction.CopyAction)
    APPLICATION.processEvents()

    destination = workspace.photo_album(30)
    assert destination is not None and destination.photo_ids == expected_ids
    assert workspace.edit_revision != revision
    assert workspace.snapshot is source_snapshot
    assert workspace.photo_album(20) == source_album
    assert albums.currentIndex().row() == source_album_row
    assert albums.model().index(2, 0).data(PhotoAlbumRole.PHOTO_COUNT) == len(
        expected_ids
    )
    albums.setCurrentIndex(albums.model().index(2, 0))
    assert _photo_ids(grid) == expected_ids


@pytest.mark.parametrize(
    ("source_actions", "selection_mode"), [(False, False), (False, True), (True, True)]
)
def test_read_only_and_sync_photo_sidebars_do_not_accept_drops(
    browser: _Browser, source_actions: bool, selection_mode: bool
) -> None:
    context = browser.context
    provider = browser.window.findChild(PhotoPixmapProvider)
    assert provider is not None
    page = PhotoPage(
        context.library_workspace,
        context.settings,
        context.theme_manager,
        provider,
        source_actions=source_actions,
        selection_mode=selection_mode,
    )
    try:
        albums = page.findChild(QListView, "photoAlbumList")
        assert albums is not None
        assert not albums.acceptDrops()
        assert albums.dragDropMode() is QAbstractItemView.DragDropMode.NoDragDrop
    finally:
        page.close()
        page.deleteLater()


def test_photo_toolbar_searches_and_sorts_the_current_album(
    browser: _Browser,
) -> None:
    photo_button = next(
        button
        for button in browser.window.findChildren(QPushButton)
        if button.property("pageId") == PageId.PHOTOS.value
    )
    photo_button.click()
    APPLICATION.processEvents()

    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    search = browser.page.findChild(SearchField, "photosSearch")
    sort = browser.page.findChild(AppComboBox, "photosSort")
    empty = browser.page.findChild(QLabel, "photoBrowserEmpty")
    stack = browser.page.findChild(QStackedWidget, "photoGridStack")
    assert grid is not None and search is not None and sort is not None
    assert empty is not None and stack is not None
    assert search.isVisible() and search.placeholderText() == "Search Photos"
    assert sort.isVisible() and sort.accessibleName() == "Sort Photos"
    assert tuple(
        (sort.itemText(index), sort.itemData(index)) for index in range(sort.count())
    ) == (
        ("Photo order", "source_order"),
        ("Newest first", "date_taken"),
        ("Highest rated", "rating"),
        ("Largest files", "source_size"),
        ("", None),
        ("Ascending", "__sort_ascending__"),
        ("Descending", "__sort_descending__"),
    )

    search.set_query("img_0003.jpg")
    search.queryChanged.emit("img_0003.jpg")
    APPLICATION.processEvents()
    assert _photo_ids(grid) == (3,)

    search.set_query("missing")
    search.queryChanged.emit("missing")
    APPLICATION.processEvents()
    assert stack.currentWidget() is empty
    assert empty.text() == "No Photos match your search."

    search.set_query("")
    search.queryChanged.emit("")
    sort.setCurrentIndex(sort.findData("rating"))
    APPLICATION.processEvents()
    assert stack.currentWidget() is grid
    assert _photo_ids(grid) == (3, 2, 1)

    sort.setCurrentIndex(sort.findText("Descending"))
    APPLICATION.processEvents()
    assert _photo_ids(grid) == (1, 2, 3)
    assert sort.currentData() == "rating"

    sort.setCurrentIndex(sort.findText("Ascending"))
    APPLICATION.processEvents()
    assert _photo_ids(grid) == (3, 2, 1)

    sort.setCurrentIndex(sort.findData("source_order"))
    APPLICATION.processEvents()
    assert _photo_ids(grid) == (1, 2, 3)


def test_photo_header_creates_and_selects_an_empty_album(
    browser: _Browser,
) -> None:
    create = browser.page.findChild(ActionButton, "photoCreateAlbum")
    albums = browser.page.findChild(QListView, "photoAlbumList")
    assert create is not None and albums is not None
    assert create.text() == "New Album"
    assert create.accessibleName() == "Create a new Photo Album"
    assert create.isEnabled()

    def complete_dialog() -> None:
        dialog = browser.page.findChild(PhotoAlbumEditorDialog, "photoAlbumEditor")
        assert dialog is not None and dialog.isVisible()
        assert dialog.minimumWidth() >= 400
        layout = dialog.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        assert margins.left() == margins.top() == LAYOUT.space_lg
        buttons = dialog.findChild(QDialogButtonBox, "photoAlbumEditorButtons")
        assert buttons is not None
        submit = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert submit.property("kind") == "primary"
        assert cancel.property("kind") == "secondary"
        dialog.name.setText("  New favorites  ")
        assert submit.isEnabled()
        dialog.accept()

    QTimer.singleShot(0, complete_dialog)

    create.click()
    APPLICATION.processEvents()

    assert albums.model().rowCount() == 4
    assert albums.currentIndex().data(PhotoAlbumRole.NAME) == "New favorites"
    assert albums.currentIndex().data(PhotoAlbumRole.PHOTO_COUNT) == 0
    assert browser.context.library_workspace.dirty


def test_photo_album_creation_action_tracks_workspace_availability(
    browser: _Browser,
) -> None:
    create = browser.page.findChild(ActionButton, "photoCreateAlbum")
    assert create is not None and create.isEnabled()

    browser.context.library_workspace.set_locked(True)
    APPLICATION.processEvents()
    assert not create.isEnabled()
    assert create.toolTip() == "Wait for the current Library save to finish."

    browser.context.library_workspace.set_locked(False)
    browser.context.library_workspace.load(LibrarySnapshot())
    APPLICATION.processEvents()
    assert not create.isEnabled()
    assert create.toolTip() == "Choose an iPod with a readable Photo Database."


def test_grid_selection_populates_inspector_metadata_and_format_picker(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    inspector = browser.page.findChild(PhotoInspector, "photoInspector")
    assert grid is not None and inspector is not None

    grid.setCurrentIndex(grid.model().index(2, 0))
    APPLICATION.processEvents()

    title = inspector.findChild(QLabel, "photoInspectorTitle")
    metadata = inspector.findChild(QTreeWidget, "photoMetadata")
    assert title is not None and title.text() == "Photo 3"
    assert inspector.photo_id == 3
    assert inspector.selected_format_id == 902
    assert metadata is not None
    assert tuple(item.text(0) for item in _top_level_items(metadata)) == (
        "Photo",
        "Storage",
        "Selected Format",
        "All Device Formats",
    )
    assert _metadata_section(metadata, "Photo") == {
        "Photo ID": "3",
        "Albums": "Photo Library, Road trip",
        "Rating": "80 / 100",
        "Original date": "2023-11-14 22:13:25 UTC",
        "Taken date": "2023-11-14 22:13:26 UTC",
    }
    selected = _metadata_section(metadata, "Selected Format")
    assert selected["Format ID"] == "902"
    assert selected["Resolution"] == "640 x 480"
    assert selected["File"] == _LARGE.relative_path
    all_formats = next(
        item
        for item in _top_level_items(metadata)
        if item.text(0) == "All Device Formats"
    )
    all_format_labels: list[str] = []
    for index in range(all_formats.childCount()):
        child = all_formats.child(index)
        assert child is not None
        all_format_labels.append(child.text(0))
    assert tuple(all_format_labels) == (
        "Format 901",
        "Full Resolution",
        "Format 902",
    )

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    format_buttons = tuple(
        button
        for button in inspector.findChildren(ActionButton)
        if button.objectName().startswith("photoFormat")
    )
    assert tuple(button.text() for button in format_buttons) == (
        "902",
        "901",
        "Full res",
    )
    full_resolution = format_buttons[2]
    assert full_resolution.objectName() == "photoFormatFullResolution"
    assert full_resolution.accessibleName() == "Full-resolution Photo"
    assert full_resolution.toolTip() == "Show the full-resolution Photo"
    selected_formats: list[int] = []
    inspector.formatSelected.connect(selected_formats.append)

    format_buttons[1].click()
    APPLICATION.processEvents()

    assert inspector.selected_format_id == 901
    assert selected_formats == [901]
    assert _metadata_section(metadata, "Selected Format")["Resolution"] == "160 x 120"

    full_resolution.click()
    APPLICATION.processEvents()

    assert inspector.selected_format_id == FULL_RESOLUTION_REQUEST_ID
    assert selected_formats == [901, FULL_RESOLUTION_REQUEST_ID]
    selected = _metadata_section(metadata, "Selected Format")
    assert selected["Kind"] == "Full resolution"
    assert selected["Resolution"] == "4032 x 3024"
    assert selected["File"] == _FULL_RESOLUTION.relative_path
    assert "Format ID" not in selected


def test_full_resolution_chip_only_appears_for_a_retained_original(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    inspector = browser.page.findChild(PhotoInspector, "photoInspector")
    assert grid is not None and inspector is not None

    grid.setCurrentIndex(grid.model().index(0, 0))
    APPLICATION.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert inspector.findChild(ActionButton, "photoFormatFullResolution") is None

    grid.setCurrentIndex(grid.model().index(2, 0))
    APPLICATION.processEvents()
    assert inspector.findChild(ActionButton, "photoFormatFullResolution") is not None


def test_photo_context_menu_preserves_or_replaces_the_grid_selection(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    menu = browser.page.findChild(QMenu, "photoContextMenu")
    assert grid is not None and menu is not None
    selection = grid.selectionModel()
    selection.select(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    selection.select(
        grid.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select,
    )

    second_position = grid.visualRect(grid.model().index(1, 0)).center()
    grid.customContextMenuRequested.emit(second_position)
    APPLICATION.processEvents()

    assert menu.isVisible()
    assert [index.row() for index in selection.selectedIndexes()] == [0, 1]
    assert tuple(action.objectName() for action in menu.actions()) == (
        "photoEditMetadata",
        "photoExport",
        "photoManageAlbums",
        "",
        "photoDelete",
    )
    assert tuple(
        action.text() for action in menu.actions() if not action.isSeparator()
    ) == (
        "Edit Metadata…",
        "Export Selected Photos…",
        "Manage Albums…",
        "Delete Photos…",
    )
    actions = tuple(action for action in menu.actions() if not action.isSeparator())
    assert all(action.isEnabled() for action in actions)
    assert actions[0].shortcut().toString() == "Ctrl+E"
    menu.hide()

    selection.setCurrentIndex(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    grid.customContextMenuRequested.emit(second_position)
    APPLICATION.processEvents()

    assert [index.row() for index in selection.selectedIndexes()] == [1]
    menu.hide()


def test_photo_metadata_editor_applies_only_explicit_fields_to_the_batch(
    browser: _Browser,
) -> None:
    source = browser.context.library_workspace.snapshot
    assert source is not None
    dialog = PhotoMetadataEditorDialog(
        browser.context.library_workspace,
        (1, 2),
        browser.page,
    )
    try:
        assert dialog.windowTitle() == "Edit 2 Photos"
        assert tuple(dialog.rows) == ("rating", "original_date", "taken_date")
        assert dialog.findChild(QFrame, "metadataEditorHeader") is not None
        navigation = dialog.findChild(QListView, "metadataSectionNav")
        assert navigation is not None
        assert tuple(
            navigation.model().index(row, 0).data()
            for row in range(navigation.model().rowCount())
        ) == ("Metadata", "Technical details")

        rating = dialog.rows["rating"]
        original_date = dialog.rows["original_date"]
        assert rating.mixed and original_date.mixed
        assert isinstance(rating.editor, QLineEdit)
        assert isinstance(original_date.editor, QLineEdit)
        assert rating.editor.text() == original_date.editor.text() == ""

        rating.editor.setText("90")
        original_date.editor.setText("1700001234")
        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        photos = browser.context.library_workspace.photos
        assert photos is not None
        assert tuple(photo.rating for photo in photos.photos) == (90, 90, 80)
        assert tuple(photo.original_date for photo in photos.photos) == (
            1_700_001_234,
            1_700_001_234,
            1_700_000_005,
        )
        assert tuple(photo.taken_date for photo in photos.photos) == (
            1_700_000_002,
            1_700_000_004,
            1_700_000_006,
        )
        source_photos = source.photos
        assert source_photos is not None
        assert source_photos is _PHOTOS
        assert source_photos.photos[0].rating == 40
    finally:
        dialog.close()


def test_photo_metadata_editor_rejects_invalid_and_stale_edits(
    browser: _Browser,
) -> None:
    workspace = browser.context.library_workspace
    invalid = PhotoMetadataEditorDialog(workspace, (1,), browser.page)
    try:
        rating = invalid.rows["rating"]
        assert isinstance(rating.editor, QLineEdit)
        rating.editor.setText("101")
        invalid.accept()
        error = invalid.findChild(QLabel, "metadataEditError")
        assert error is not None and "Rating" in error.text()
        assert invalid.result() != QDialog.DialogCode.Accepted
        assert not workspace.dirty
    finally:
        invalid.close()

    stale = PhotoMetadataEditorDialog(workspace, (1,), browser.page)
    try:
        photo = workspace.photo(2)
        assert photo is not None
        workspace.replace_photo(replace(photo, rating=100), workspace.edit_revision)
        stale.accept()
        error = stale.findChild(QLabel, "metadataEditError")
        assert error is not None and "Library changed" in error.text()
        assert stale.result() != QDialog.DialogCode.Accepted
    finally:
        stale.close()


def test_photo_context_menu_opens_metadata_editor_for_the_selection(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    menu = browser.page.findChild(QMenu, "photoContextMenu")
    assert grid is not None and menu is not None
    selection = grid.selectionModel()
    selection.select(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    selection.select(
        grid.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.Select,
    )
    grid.customContextMenuRequested.emit(
        grid.visualRect(grid.model().index(2, 0)).center()
    )
    edit = next(
        action
        for action in menu.actions()
        if action.objectName() == "photoEditMetadata"
    )

    edit.trigger()
    APPLICATION.processEvents()

    dialog = browser.page.findChild(PhotoMetadataEditorDialog, "photoMetadataEditor")
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowTitle() == "Edit 2 Photos"
    dialog.reject()


def test_delete_selected_photos_is_confirmed_and_staged(
    browser: _Browser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    menu = browser.page.findChild(QMenu, "photoContextMenu")
    assert grid is not None and menu is not None
    selection = grid.selectionModel()
    selection.select(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    selection.select(
        grid.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.Select,
    )
    questions: list[tuple[str, str]] = []

    def confirm(
        _parent: object,
        title: str,
        message: str,
        _buttons: object,
        _default: object,
    ) -> QMessageBox.StandardButton:
        questions.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    grid.customContextMenuRequested.emit(
        grid.visualRect(grid.model().index(2, 0)).center()
    )
    delete = next(
        action for action in menu.actions() if action.objectName() == "photoDelete"
    )

    assert delete.isEnabled()
    delete.trigger()
    APPLICATION.processEvents()

    photos = browser.context.library_workspace.photos
    assert photos is not None
    assert tuple(photo.photo_id for photo in photos.photos) == (2,)
    assert tuple(album.photo_ids for album in photos.albums) == ((2,), (), ())
    assert browser.context.library_workspace.delete_omissions
    assert questions and questions[0][0] == "Delete Selected Photos?"
    assert questions[0][1] == (
        "Remove these 2 Photos from every Photo Album and delete any unshared "
        "full-resolution files from the iPod?"
    )


def test_manage_albums_dialog_uses_collages_and_toggles_selected_photos(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    menu = browser.page.findChild(QMenu, "photoContextMenu")
    assert grid is not None and menu is not None
    selection = grid.selectionModel()
    selection.select(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    selection.select(
        grid.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.Select,
    )
    grid.customContextMenuRequested.emit(
        grid.visualRect(grid.model().index(2, 0)).center()
    )
    manage = next(
        action
        for action in menu.actions()
        if action.objectName() == "photoManageAlbums"
    )
    manage.trigger()
    APPLICATION.processEvents()

    dialog = browser.page.findChild(PhotoAlbumManagerDialog, "photoAlbumManager")
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowTitle() == "Manage Albums"
    albums = dialog.findChild(
        PhotoAlbumMembershipGrid,
        "photoAlbumMembershipGrid",
    )
    assert albums is not None and albums.model().rowCount() == 2
    assert albums.selectionMode() is QAbstractItemView.SelectionMode.NoSelection
    assert not albums.selectionModel().selectedIndexes()
    assert tuple(
        albums.model().index(row, 0).data(PhotoAlbumMembershipRole.NAME)
        for row in range(albums.model().rowCount())
    ) == ("Road trip", "Empty album")
    assert albums.model().index(0, 0).data(
        PhotoAlbumMembershipRole.PREVIEW_PHOTO_IDS
    ) == (3, 1, 0, 0)
    assert albums.model().index(0, 0).data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.Checked
    )
    assert albums.model().index(1, 0).data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.Unchecked
    )

    empty_index = albums.model().index(1, 0)
    option = QStyleOptionViewItem()
    option.initFrom(albums)
    option.rect = albums.visualRect(empty_index)
    checkbox = photo_album_checkbox_rect(
        option,
        browser.context.theme_manager.typography,
    )
    assert checkbox.width() == checkbox.height() == 36
    assert option.rect.contains(checkbox.toRect())
    card = library_card_rect(option, browser.context.theme_manager.typography)
    card_click = card.topLeft().toPoint() + QPoint(20, 20)
    assert not checkbox.contains(card_click)
    QTest.mouseClick(
        albums.viewport(),
        Qt.MouseButton.LeftButton,
        pos=card_click,
    )
    APPLICATION.processEvents()

    empty_album = browser.context.library_workspace.photo_album(30)
    assert empty_album is not None and empty_album.photo_ids == (1, 3)
    assert not albums.selectionModel().selectedIndexes()

    checked_index = albums.model().index(0, 0)
    option.rect = albums.visualRect(checked_index)
    card = library_card_rect(option, browser.context.theme_manager.typography)
    card_click = card.topLeft().toPoint() + QPoint(20, 20)
    QTest.mouseClick(
        albums.viewport(),
        Qt.MouseButton.LeftButton,
        pos=card_click,
    )
    APPLICATION.processEvents()
    road_trip = browser.context.library_workspace.photo_album(20)
    assert road_trip is not None and road_trip.photo_ids == ()
    dialog.accept()


def test_photo_export_requests_the_selected_photos_in_grid_order(
    browser: _Browser,
) -> None:
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    menu = browser.page.findChild(QMenu, "photoContextMenu")
    assert grid is not None and menu is not None
    selection = grid.selectionModel()
    selection.select(
        grid.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    selection.select(
        grid.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select,
    )
    requested: list[tuple[Photo, ...]] = []
    browser.page.photoExportRequested.disconnect()
    browser.page.photoExportRequested.connect(requested.append)

    grid.customContextMenuRequested.emit(
        grid.visualRect(grid.model().index(2, 0)).center()
    )
    export = next(
        action for action in menu.actions() if action.objectName() == "photoExport"
    )
    export.trigger()

    assert tuple(photo.photo_id for photo in requested[0]) == (1, 3)


def test_photo_album_context_menu_exports_complete_membership_order(
    browser: _Browser,
) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    menu = browser.page.findChild(QMenu, "photoAlbumContextMenu")
    assert albums is not None and menu is not None
    requested: list[tuple[str, tuple[Photo, ...]]] = []

    def capture_request(name: str, value: object) -> None:
        assert isinstance(value, tuple)
        requested.append((name, cast("tuple[Photo, ...]", value)))

    browser.page.photoAlbumExportRequested.disconnect()
    browser.page.photoAlbumExportRequested.connect(capture_request)

    album_index = albums.model().index(1, 0)
    albums.customContextMenuRequested.emit(albums.visualRect(album_index).center())
    export = next(
        action for action in menu.actions() if action.objectName() == "photoAlbumExport"
    )
    rename = next(
        action for action in menu.actions() if action.objectName() == "photoAlbumRename"
    )
    delete = next(
        action for action in menu.actions() if action.objectName() == "photoAlbumDelete"
    )

    assert export.text() == "Export Photo Album…"
    assert export.isEnabled()
    assert rename.isEnabled() and delete.isEnabled()
    export.trigger()
    assert requested[0][0] == "Road trip"
    assert tuple(photo.photo_id for photo in requested[0][1]) == (3, 1)

    all_index = albums.model().index(0, 0)
    albums.customContextMenuRequested.emit(albums.visualRect(all_index).center())
    assert export.text() == "Export All Photos…"
    assert not rename.isEnabled() and not delete.isEnabled()
    assert rename.toolTip() == "All Photos cannot be renamed or deleted."
    export.trigger()
    assert requested[1][0] == "All Photos"
    assert tuple(photo.photo_id for photo in requested[1][1]) == (1, 2, 3)


def test_photo_album_context_menu_renames_the_album(browser: _Browser) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    menu = browser.page.findChild(QMenu, "photoAlbumContextMenu")
    assert albums is not None and menu is not None
    album_index = albums.model().index(1, 0)
    albums.customContextMenuRequested.emit(albums.visualRect(album_index).center())
    rename = next(
        action for action in menu.actions() if action.objectName() == "photoAlbumRename"
    )

    def complete_dialog() -> None:
        dialog = browser.page.findChild(PhotoAlbumEditorDialog, "photoAlbumEditor")
        assert dialog is not None and dialog.isVisible()
        assert dialog.windowTitle() == "Rename Photo Album"
        assert dialog.name.text() == "Road trip"
        buttons = dialog.findChild(QDialogButtonBox, "photoAlbumEditorButtons")
        assert buttons is not None
        assert buttons.button(QDialogButtonBox.StandardButton.Save).text() == (
            "Rename Album"
        )
        dialog.name.setText("  Summer trip  ")
        dialog.accept()

    QTimer.singleShot(0, complete_dialog)
    rename.trigger()
    APPLICATION.processEvents()

    renamed = browser.context.library_workspace.photo_album(20)
    assert renamed is not None
    assert renamed.name == "Summer trip"
    assert renamed.photo_ids == (3, 1)
    assert albums.currentIndex().data(PhotoAlbumRole.NAME) == "Summer trip"


def test_photo_album_context_menu_deletes_only_the_album(
    browser: _Browser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    menu = browser.page.findChild(QMenu, "photoAlbumContextMenu")
    assert albums is not None and menu is not None
    album_index = albums.model().index(1, 0)
    albums.customContextMenuRequested.emit(albums.visualRect(album_index).center())
    delete = next(
        action for action in menu.actions() if action.objectName() == "photoAlbumDelete"
    )
    questions: list[tuple[str, str]] = []

    def confirm(
        _parent: object,
        title: str,
        message: str,
        _buttons: object,
        _default: object,
    ) -> QMessageBox.StandardButton:
        questions.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    delete.trigger()
    APPLICATION.processEvents()

    photos = browser.context.library_workspace.photos
    assert photos is not None
    assert tuple(photo.photo_id for photo in photos.photos) == (1, 2, 3)
    assert tuple(album.album_id for album in photos.albums) == (10, 30)
    assert albums.currentIndex().data(PhotoAlbumRole.IS_ALL_PHOTOS) is True
    assert browser.context.library_workspace.delete_omissions
    assert questions[0][0] == "Delete Photo Album?"
    assert "removes the Photos from this album only" in questions[0][1]
    assert "Photos themselves stay on the iPod" in questions[0][1]


def test_empty_and_missing_photo_libraries_have_distinct_states(
    browser: _Browser,
) -> None:
    empty = browser.page.findChild(QLabel, "photoBrowserEmpty")
    stack = browser.page.findChild(QStackedWidget, "photoGridStack")
    albums = browser.page.findChild(QListView, "photoAlbumList")
    inspector = browser.page.findChild(PhotoInspector, "photoInspector")
    assert empty is not None and stack is not None
    assert albums is not None and inspector is not None

    browser.context.library_workspace.load(LibrarySnapshot())
    APPLICATION.processEvents()

    assert stack.currentWidget() is empty
    assert empty.text() == "This iPod has no readable Photo Database."
    assert albums.model().rowCount() == 0
    assert inspector.photo_id is None

    browser.context.library_workspace.load(
        LibrarySnapshot(photos=PhotoLibrary()),
    )
    APPLICATION.processEvents()

    assert stack.currentWidget() is empty
    assert empty.text() == "This iPod has no Photos."
    assert albums.model().rowCount() == 1
    assert albums.model().index(0, 0).data() == "All Photos"
    assert inspector.photo_id is None


def test_photo_selection_survives_a_workspace_draft_refresh(
    browser: _Browser,
) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    inspector = browser.page.findChild(PhotoInspector, "photoInspector")
    assert albums is not None and grid is not None and inspector is not None

    albums.setCurrentIndex(albums.model().index(1, 0))
    grid.setCurrentIndex(grid.model().index(1, 0))
    photo = browser.context.library_workspace.photo(1)
    assert photo is not None

    browser.context.library_workspace.replace_photo(
        replace(photo, rating=100),
        browser.context.library_workspace.edit_revision,
    )
    APPLICATION.processEvents()

    assert albums.currentIndex().data(PhotoAlbumRole.ID) == 20
    assert grid.currentIndex().data(PhotoRole.ID) == 1
    assert inspector.photo_id == 1
    metadata = inspector.findChild(QTreeWidget, "photoMetadata")
    assert metadata is not None
    assert _metadata_section(metadata, "Photo")["Rating"] == "100 / 100"


def test_photo_selection_resets_for_a_new_workspace_generation(
    browser: _Browser,
) -> None:
    albums = browser.page.findChild(QListView, "photoAlbumList")
    grid = browser.page.findChild(PhotoGridView, "photoGrid")
    inspector = browser.page.findChild(PhotoInspector, "photoInspector")
    assert albums is not None and grid is not None and inspector is not None

    albums.setCurrentIndex(albums.model().index(1, 0))
    grid.setCurrentIndex(grid.model().index(1, 0))
    assert albums.currentIndex().data(PhotoAlbumRole.ID) == 20
    assert grid.currentIndex().data(PhotoRole.ID) == 1

    next_library = replace(
        _PHOTOS,
        photos=(_PHOTOS.photos[2], _PHOTOS.photos[1], _PHOTOS.photos[0]),
    )
    browser.context.library_workspace.load(LibrarySnapshot(photos=next_library))
    APPLICATION.processEvents()

    assert albums.currentIndex().data(PhotoAlbumRole.IS_ALL_PHOTOS) is True
    assert grid.currentIndex().data(PhotoRole.ID) == 3
    assert inspector.photo_id == 3
