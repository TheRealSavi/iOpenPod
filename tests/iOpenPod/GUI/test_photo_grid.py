"""Photo grid interaction and repaint behavior."""

from typing import TYPE_CHECKING, ClassVar, cast
from unittest.mock import patch

from PySide6.QtCore import (
    QItemSelectionModel,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    Qt,
    Signal,
)
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication
from pytest import MonkeyPatch

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import PhotoSelectionMimeData, dropped_photos
from iOpenPod.app.models.photo_list_model import PhotoListModel
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets import photo_grid as photo_grid_module
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iPodDB.library import LibrarySnapshot, Photo, PhotoAlbum, PhotoLibrary

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _PhotoProvider(QObject):
    photoChanged = Signal(int)
    cleared = Signal()
    capacityAvailable = Signal()

    def pixmap(
        self,
        _photo_id: int,
        _logical_size: int,
        _device_pixel_ratio: float,
        *,
        format_id: int | None = None,
    ) -> QPixmap | None:
        del format_id
        return None


class _RecordingDrag:
    instances: ClassVar[list["_RecordingDrag"]] = []

    def __init__(self, source: object) -> None:
        self.source = source
        self.mime_data: QMimeData | None = None
        self.pixmap = QPixmap()
        self.hot_spot = QPoint()
        self.action = Qt.DropAction.IgnoreAction
        self.instances.append(self)

    def setMimeData(self, mime_data: QMimeData) -> None:
        self.mime_data = mime_data

    def setPixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap

    def setHotSpot(self, hot_spot: QPoint) -> None:
        self.hot_spot = hot_spot

    def exec(self, action: Qt.DropAction) -> Qt.DropAction:
        self.action = action
        return action


def _grid_with_photos() -> tuple[
    LibraryWorkspace,
    ThemeManager,
    PhotoListModel,
    PhotoGridView,
]:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(photos=PhotoLibrary(photos=(Photo(10), Photo(20), Photo(30))))
    )
    model = PhotoListModel(workspace)
    provider = _PhotoProvider()
    theme = ThemeManager(
        APPLICATION,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    grid = PhotoGridView(model, theme, cast("PhotoPixmapProvider", provider))
    grid.set_library_workspace(workspace)
    grid.resize(900, 600)
    grid.show()
    APPLICATION.processEvents()
    return workspace, theme, model, grid


def test_grid_multi_selection_creates_a_revision_bound_photo_drag(
    monkeypatch: MonkeyPatch,
) -> None:
    workspace, theme, model, grid = _grid_with_photos()
    monkeypatch.setattr(photo_grid_module, "QDrag", _RecordingDrag)
    _RecordingDrag.instances.clear()

    try:
        selection = grid.selectionModel()
        selection.select(
            model.index(0, 0),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        selection.select(model.index(2, 0), QItemSelectionModel.SelectionFlag.Select)
        grid.startDrag(Qt.DropAction.CopyAction)
        drag = _RecordingDrag.instances[-1]

        assert grid.selectionMode() is QAbstractItemView.SelectionMode.ExtendedSelection
        assert grid.dragDropMode() is QAbstractItemView.DragDropMode.DragOnly
        assert isinstance(drag.mime_data, PhotoSelectionMimeData)
        assert drag.mime_data.photo_ids == (10, 30)
        assert dropped_photos(drag.mime_data, workspace) == (
            workspace.photo(10),
            workspace.photo(30),
        )
        assert not drag.pixmap.isNull()
        assert drag.action is Qt.DropAction.CopyAction

        workspace.replace_photo(Photo(10, rating=20), workspace.edit_revision)
        assert dropped_photos(drag.mime_data, workspace) is None
    finally:
        grid.close()
        theme.close()


def test_left_drag_on_a_photo_card_starts_a_photo_drag(
    monkeypatch: MonkeyPatch,
) -> None:
    _workspace, theme, model, grid = _grid_with_photos()
    monkeypatch.setattr(photo_grid_module, "QDrag", _RecordingDrag)
    _RecordingDrag.instances.clear()

    try:
        start = grid.visualRect(model.index(0, 0)).center()
        finish = start + QPoint(QApplication.startDragDistance() + 4, 0)
        _send_mouse_event(
            grid,
            QMouseEvent.Type.MouseButtonPress,
            start,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        _send_mouse_event(
            grid,
            QMouseEvent.Type.MouseMove,
            finish,
            button=Qt.MouseButton.NoButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        _send_mouse_event(
            grid,
            QMouseEvent.Type.MouseButtonRelease,
            finish,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.NoButton,
        )

        assert len(_RecordingDrag.instances) == 1
        drag = _RecordingDrag.instances[0]
        assert isinstance(drag.mime_data, PhotoSelectionMimeData)
        assert not drag.pixmap.isNull()
        assert drag.action is Qt.DropAction.CopyAction
    finally:
        grid.close()
        theme.close()


def test_grid_box_selection_requires_shift_drag() -> None:
    _workspace, theme, model, grid = _grid_with_photos()

    try:
        first = model.index(0, 0)
        start = QPoint(grid.viewport().width() - 2, grid.viewport().height() - 2)
        finish = grid.visualRect(first).center()
        assert not grid.indexAt(start).isValid()

        grid.selectionModel().select(
            first,
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        _drag_empty_space(grid, start, finish, Qt.KeyboardModifier.NoModifier)
        assert not grid.selectionModel().selectedIndexes()

        _press_and_move_empty_space(
            grid,
            start,
            finish,
            Qt.KeyboardModifier.ShiftModifier,
        )
        assert grid.state() is QAbstractItemView.State.DragSelectingState
        _release_empty_space(grid, finish, Qt.KeyboardModifier.ShiftModifier)
        assert grid.selectionModel().selectedIndexes()
    finally:
        grid.close()
        theme.close()


def _send_mouse_event(
    grid: PhotoGridView,
    event_type: QMouseEvent.Type,
    position: QPoint,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    APPLICATION.sendEvent(
        grid.viewport(),
        QMouseEvent(
            event_type,
            QPointF(position),
            QPointF(grid.viewport().mapToGlobal(position)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _drag_empty_space(
    grid: PhotoGridView,
    start: QPoint,
    finish: QPoint,
    modifiers: Qt.KeyboardModifier,
) -> None:
    _press_and_move_empty_space(grid, start, finish, modifiers)
    _release_empty_space(grid, finish, modifiers)


def _press_and_move_empty_space(
    grid: PhotoGridView,
    start: QPoint,
    finish: QPoint,
    modifiers: Qt.KeyboardModifier,
) -> None:
    grid.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(start),
            QPointF(grid.viewport().mapToGlobal(start)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
    )
    grid.mouseMoveEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(finish),
            QPointF(grid.viewport().mapToGlobal(finish)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
    )


def _release_empty_space(
    grid: PhotoGridView,
    position: QPoint,
    modifiers: Qt.KeyboardModifier,
) -> None:
    grid.mouseReleaseEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(position),
            QPointF(grid.viewport().mapToGlobal(position)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            modifiers,
        )
    )


def test_grid_repaints_every_visible_duplicate_photo_occurrence() -> None:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            photos=PhotoLibrary(
                photos=(Photo(10), Photo(30)),
                albums=(PhotoAlbum(201, "Repeated", (30, 10, 30)),),
            )
        )
    )
    model = PhotoListModel(workspace)
    model.set_album_id(201)
    provider = _PhotoProvider()
    theme = ThemeManager(
        APPLICATION,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    grid = PhotoGridView(
        model,
        theme,
        cast("PhotoPixmapProvider", provider),
    )
    grid.resize(900, 600)
    grid.show()
    APPLICATION.processEvents()

    expected = tuple(grid.visualRect(model.index(row, 0)) for row in (0, 2))
    assert all(
        rect.isValid() and rect.intersects(grid.viewport().rect()) for rect in expected
    )

    try:
        with (
            patch.object(
                model,
                "indexes_for_photo",
                wraps=model.indexes_for_photo,
            ) as indexes_for_photo,
            patch.object(grid.viewport(), "update") as update,
        ):
            provider.photoChanged.emit(30)

        indexes_for_photo.assert_called_once_with(30)
        assert tuple(call.args[0] for call in update.call_args_list) == expected
    finally:
        grid.close()
        theme.close()
