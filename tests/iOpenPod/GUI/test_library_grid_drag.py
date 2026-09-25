"""Album and collection cards share the Library Track drag contract."""

from typing import ClassVar

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView
from pytest import MonkeyPatch
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.collection_list_model import (
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.app.models.library_drag import TrackSelectionMimeData, dropped_tracks
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets import library_drag_grid as library_drag_grid_module
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iPodDB.library import LibrarySnapshot, Playlist, Track

_TRACKS = (
    Track(1, "First", "Artist A", "Album A", 180_000),
    Track(2, "Second", "Artist A", "Album A", 200_000),
    Track(3, "Third", "Artist B", "Album B", 220_000),
)


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


def test_album_and_collection_cards_drag_all_resolved_tracks(
    monkeypatch: MonkeyPatch,
) -> None:
    context = build_context()
    context.library_workspace.load(
        LibrarySnapshot(tuple(reversed(_TRACKS)), (Playlist(10, "Destination"),))
    )
    context.track_model.replace_tracks(tuple(reversed(_TRACKS)))
    window = MainWindow(context, auto_discover=False)
    monkeypatch.setattr(library_drag_grid_module, "QDrag", _RecordingDrag)
    _RecordingDrag.instances.clear()

    try:
        window.show()
        APPLICATION.processEvents()
        album_grid = window.findChild(AlbumGridView, "albumGrid")
        artist_grid = window.findChild(CollectionGridView, "artistsCollectionGrid")
        assert album_grid is not None and artist_grid is not None

        album_index = next(
            album_grid.model().index(row, 0)
            for row in range(album_grid.model().rowCount())
            if isinstance(
                summary := album_grid.model().index(row, 0).data(AlbumRole.SUMMARY),
                AlbumSummary,
            )
            and summary.title == "Album A"
        )
        album_grid.setCurrentIndex(album_index)
        album_grid.startDrag(Qt.DropAction.CopyAction)
        album_drag = _RecordingDrag.instances[-1]

        assert album_grid.dragDropMode() is QAbstractItemView.DragDropMode.DragOnly
        assert isinstance(album_drag.mime_data, TrackSelectionMimeData)
        assert album_drag.mime_data.track_ids == (1, 2)
        assert (
            dropped_tracks(album_drag.mime_data, context.library_workspace)
            == _TRACKS[:2]
        )
        assert not album_drag.pixmap.isNull()
        assert album_drag.action is Qt.DropAction.CopyAction

        artist_index = next(
            artist_grid.model().index(row, 0)
            for row in range(artist_grid.model().rowCount())
            if isinstance(
                summary := artist_grid.model()
                .index(row, 0)
                .data(CollectionRole.SUMMARY),
                CollectionSummary,
            )
            and summary.title == "Artist A"
        )
        artist_grid.setCurrentIndex(artist_index)
        artist_grid.startDrag(Qt.DropAction.CopyAction)
        artist_drag = _RecordingDrag.instances[-1]

        assert isinstance(artist_drag.mime_data, TrackSelectionMimeData)
        assert artist_drag.mime_data.track_ids == (1, 2)
        assert (
            dropped_tracks(artist_drag.mime_data, context.library_workspace)
            == _TRACKS[:2]
        )
        assert not artist_drag.pixmap.isNull()
        assert artist_drag.action is Qt.DropAction.CopyAction
    finally:
        window.close()
        context.shutdown()


def test_double_click_queues_clicked_album_and_collection_tracks() -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(tuple(reversed(_TRACKS))))
    context.track_model.replace_tracks(tuple(reversed(_TRACKS)))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        album_grid = window.findChild(AlbumGridView, "albumGrid")
        artist_grid = window.findChild(CollectionGridView, "artistsCollectionGrid")
        assert album_grid is not None and artist_grid is not None

        album_index = next(
            album_grid.model().index(row, 0)
            for row in range(album_grid.model().rowCount())
            if (summary := album_grid.model().index(row, 0).data(AlbumRole.SUMMARY))
            and isinstance(summary, AlbumSummary)
            and summary.title == "Album A"
        )
        artist_index = next(
            artist_grid.model().index(row, 0)
            for row in range(artist_grid.model().rowCount())
            if (
                summary := artist_grid.model()
                .index(row, 0)
                .data(CollectionRole.SUMMARY)
            )
            and isinstance(summary, CollectionSummary)
            and summary.title == "Artist B"
        )

        album_grid.setCurrentIndex(album_index)
        current_before_activation = context.playback_controller.current_track
        assert current_before_activation is None
        album_grid.doubleClicked.emit(album_index)
        assert context.playback_controller.current_track == _TRACKS[0]
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (_TRACKS[1],)

        artist_grid.doubleClicked.emit(artist_index)
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (_TRACKS[1], _TRACKS[2])

        artist_list = window.findChild(QListView, "artistsCollectionList")
        assert artist_list is not None
        artist_list_index = next(
            artist_list.model().index(row, 0)
            for row in range(artist_list.model().rowCount())
            if (
                summary := artist_list.model()
                .index(row, 0)
                .data(CollectionRole.SUMMARY)
            )
            and isinstance(summary, CollectionSummary)
            and summary.title == "Artist A"
        )
        artist_list.doubleClicked.emit(artist_list_index)
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (_TRACKS[1], _TRACKS[2], _TRACKS[0], _TRACKS[1])
    finally:
        window.close()
        context.shutdown()


def test_grid_box_selection_requires_shift_drag() -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)

    try:
        window.resize(1_000, 800)
        window.show()
        APPLICATION.processEvents()
        grid = window.findChild(AlbumGridView, "albumGrid")
        assert grid is not None
        first = grid.model().index(0, 0)
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
        _release_empty_space(
            grid,
            finish,
            Qt.KeyboardModifier.ShiftModifier,
        )
        assert grid.selectionModel().selectedIndexes()
    finally:
        window.close()
        context.shutdown()


def _drag_empty_space(
    grid: AlbumGridView,
    start: QPoint,
    finish: QPoint,
    modifiers: Qt.KeyboardModifier,
) -> None:
    _press_and_move_empty_space(grid, start, finish, modifiers)
    _release_empty_space(grid, finish, modifiers)


def _press_and_move_empty_space(
    grid: AlbumGridView,
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
    grid: AlbumGridView,
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
