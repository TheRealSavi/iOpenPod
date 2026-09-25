"""History rows participate in the shared Track interactions."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QListView, QMenu, QTabWidget
from pytest import MonkeyPatch, mark
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    tracks as build_tracks,
)

from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets import playback_pane as playback_pane_module
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iPodDB.library import LibrarySnapshot


@mark.parametrize("keyboard", (False, True))
def test_history_context_menu_uses_the_target_track_instead_of_the_current_track(
    keyboard: bool,
) -> None:
    context = build_context()
    tracks = build_tracks(2)
    context.library_workspace.load(LibrarySnapshot(tracks=tracks))
    window = MainWindow(context, auto_discover=False)
    opened: list[bool] = []
    try:
        window.show()
        controller = context.playback_controller
        controller.play_now((tracks[0],))
        controller.play_now((tracks[1],))
        view = window.findChild(QListView, "playbackHistoryView")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        toggle = window.findChild(IconButton, "playerQueueToggle")
        assert view is not None and tabs is not None
        assert toggle is not None
        toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        tabs.setCurrentIndex(1)
        APPLICATION.processEvents()
        view.setCurrentIndex(view.model().index(1 if keyboard else 0, 0))
        point = view.visualRect(view.model().index(1, 0)).center()

        def use_and_close_menu() -> None:
            menu = window.findChild(QMenu, "trackContextMenu")
            opened.append(menu is not None and menu.isVisible())
            if menu is not None:
                next(
                    action
                    for action in menu.actions()
                    if action.text() == "Copy as Text"
                ).trigger()
                menu.close()

        QTimer.singleShot(0, use_and_close_menu)
        APPLICATION.sendEvent(
            view.viewport(),
            QContextMenuEvent(
                QContextMenuEvent.Reason.Keyboard
                if keyboard
                else QContextMenuEvent.Reason.Mouse,
                point,
                view.viewport().mapToGlobal(point),
            ),
        )
        APPLICATION.processEvents()

        assert opened == [True]
        assert APPLICATION.clipboard().text() == "\t".join(
            (tracks[0].title, tracks[0].artist, tracks[0].album)
        )
        assert controller.current_track == tracks[1]
        assert controller.history_model.rowCount() == 2
    finally:
        window.close()
        context.shutdown()


def test_history_context_menu_ignores_empty_space() -> None:
    context = build_context()
    track = build_tracks(1)[0]
    context.library_workspace.load(LibrarySnapshot(tracks=(track,)))
    window = MainWindow(context, auto_discover=False)
    opened: list[bool] = []
    try:
        window.show()
        context.playback_controller.enqueue(track)
        view = window.findChild(QListView, "playbackHistoryView")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        toggle = window.findChild(IconButton, "playerQueueToggle")
        assert view is not None and tabs is not None and toggle is not None
        toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        tabs.setCurrentIndex(1)
        APPLICATION.processEvents()
        view.setCurrentIndex(view.model().index(0, 0))
        point = QPoint(8, view.viewport().height() - 8)
        assert not view.indexAt(point).isValid()

        def close_unexpected_menu() -> None:
            menu = window.findChild(QMenu, "trackContextMenu")
            opened.append(menu is not None and menu.isVisible())
            if menu is not None:
                menu.close()

        QTimer.singleShot(0, close_unexpected_menu)
        APPLICATION.sendEvent(
            view.viewport(),
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse,
                point,
                view.viewport().mapToGlobal(point),
            ),
        )
        APPLICATION.processEvents()

        assert opened == [False]
        assert context.playback_controller.current_track == track
    finally:
        window.close()
        context.shutdown()


def test_dragging_a_history_row_onto_the_player_starts_its_track(
    monkeypatch: MonkeyPatch,
) -> None:
    context = build_context()
    tracks = build_tracks(2)
    context.library_workspace.load(LibrarySnapshot(tracks=tracks))
    window = MainWindow(context, auto_discover=False)
    captured: list[TrackSelectionMimeData] = []

    class FakeDrag:
        def __init__(self, _source: object) -> None:
            pass

        def setMimeData(self, data: TrackSelectionMimeData) -> None:
            captured.append(data)

        def setPixmap(self, _pixmap: object) -> None:
            pass

        def setHotSpot(self, _point: object) -> None:
            pass

        def exec(self, actions: Qt.DropAction) -> Qt.DropAction:
            assert actions == Qt.DropAction.CopyAction
            return Qt.DropAction.CopyAction

    try:
        window.show()
        controller = context.playback_controller
        controller.play_now((tracks[0],))
        controller.play_now((tracks[1],))
        history_entries = controller.history_model.entries
        view = window.findChild(QListView, "playbackHistoryView")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        toggle = window.findChild(IconButton, "playerQueueToggle")
        player = window.findChild(PlayerBar, "playerBar")
        title = window.findChild(QLabel, "playerTrackTitle")
        assert view is not None and tabs is not None
        assert player is not None and title is not None
        assert toggle is not None
        toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        tabs.setCurrentIndex(1)
        APPLICATION.processEvents()
        assert view.dragEnabled()
        assert not view.acceptDrops()
        monkeypatch.setattr(playback_pane_module, "QDrag", FakeDrag)
        start = view.visualRect(view.model().index(1, 0)).center()
        end = start + QPoint(APPLICATION.startDragDistance() + 2, 0)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        for event_type, point, button in (
            (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton),
            (QEvent.Type.MouseMove, end + QPoint(1, 0), Qt.MouseButton.NoButton),
        ):
            APPLICATION.sendEvent(
                view.viewport(),
                QMouseEvent(
                    event_type,
                    QPointF(point),
                    QPointF(view.viewport().mapToGlobal(point)),
                    button,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

        assert len(captured) == 1
        data = captured[0]
        assert isinstance(data, TrackSelectionMimeData)
        assert data.track_ids == (tracks[0].track_id,)
        assert controller.history_model.entries == history_entries
        event = QDropEvent(
            QPointF(8, 8),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        player.dropEvent(event)

        assert event.isAccepted()
        assert controller.current_track == tracks[0]
        assert title.text() == tracks[0].title
        assert controller.history_model.entries[1:] == history_entries
    finally:
        window.close()
        context.shutdown()
