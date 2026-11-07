"""Inline Album tracks use the ordinary Track drag previews and drop targets."""

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import QDrag, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
    show_albums,
)

from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    IPodLibraryViewMode,
)
from iOpenPod.app.models.library_drag import TrackSelectionMimeData, dropped_tracks
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iPodDB.library import LibrarySnapshot, Playlist, Track


@pytest.mark.parametrize("multiple", (False, True))
def test_pointer_drag_uses_standard_preview_and_all_library_drop_targets(
    monkeypatch: pytest.MonkeyPatch, multiple: bool
) -> None:
    context = build_context()
    tracks = tuple(
        Track(number, f"Song {number}", "Artist", "Album", 180_000, track_number=number)
        for number in range(1, 5)
    )
    context.library_workspace.load(
        LibrarySnapshot(tracks, (Playlist(10, "Destination"),))
    )
    context.track_model.replace_tracks(tracks)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    window = MainWindow(context, auto_discover=False)
    show_albums(window)
    drags: list[QDrag] = []

    def record_drag(drag: QDrag, action: Qt.DropAction) -> Qt.DropAction:
        drags.append(drag)
        assert action is Qt.DropAction.CopyAction
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(QDrag, "exec", record_drag)
    try:
        window.resize(1600, 950)
        window.show()
        QTest.qWait(50)
        page = window.findChild(LibraryPage, "albumsPage")
        assert page is not None
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        assert grid is not None and panel is not None
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(grid.model().index(0, 0)).center(),
        )
        QTest.qWait(280)
        view = panel.track_view
        assert view.dragEnabled()
        assert view.dragDropMode() is QAbstractItemView.DragDropMode.DragOnly
        assert view.toolTip() == ""
        assert view.model().columnCount() == 2
        first = view.model().index(0, 0)
        selection = view.selectionModel()
        for column, row in ((1, 0), (0, 1), (0, 0)) if multiple else ((0, 0),):
            selection.select(
                view.model().index(row, column),
                QItemSelectionModel.SelectionFlag.Select,
            )
        selection.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
        expected = tracks[:3] if multiple else tracks[:1]

        # Exercise Qt's real drag gesture: dragEnabled and model flags must both
        # permit it; calling startDrag directly would miss either missing flag.
        start = view.visualRect(first).center()
        finish = start + QPoint(QApplication.startDragDistance() + 20, 0)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(finish),
            QPointF(view.viewport().mapToGlobal(finish)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(view.viewport(), move)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=finish)
        assert len(drags) == 1
        drag = drags[0]
        assert drag.source() is view
        data = drag.mimeData()
        assert isinstance(data, TrackSelectionMimeData)
        assert dropped_tracks(data, context.library_workspace) == expected
        assert not drag.pixmap().isNull()
        assert drag.pixmap().height() / drag.pixmap().devicePixelRatio() == (
            44 if multiple else 72
        )

        player = window.findChild(PlayerBar)
        assert player is not None
        event = QDropEvent(
            QPointF(8, 8),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        player.dropEvent(event)
        assert event.isAccepted()
        assert context.playback_controller.current_track == expected[0]
        queue = context.playback_controller.queue_model
        assert queue.canDropMimeData(
            data, Qt.DropAction.CopyAction, -1, 0, QModelIndex()
        )
        assert queue.dropMimeData(data, Qt.DropAction.CopyAction, -1, 0, QModelIndex())
        assert (
            tuple(entry.track for entry in queue.entries)[-len(expected) :] == expected
        )

        model = next(
            model
            for model in window.findChildren(PlaylistTreeModel)
            if model.index_for_id(10).isValid()
        )
        target = model.index_for_id(10)
        assert model.dropMimeData(data, Qt.DropAction.CopyAction, -1, 0, target)
        assert context.library_workspace.tracks_for(10) == expected
        assert dropped_tracks(data, context.library_workspace) is None

        # Locked workflows retain the same refusal to start another Track drag.
        context.library_workspace.set_locked(True)
        view.startDrag(Qt.DropAction.CopyAction)
        assert len(drags) == 1
    finally:
        window.close()
        context.shutdown()
