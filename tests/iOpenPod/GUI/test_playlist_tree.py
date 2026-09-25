"""Playlist sidebar navigation and editing intents."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QTreeView,
)
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind, Track


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def _assert_unselected(sidebar: PlaylistTree) -> None:
    assert sidebar.current_playlist_id is None


class _TestPlaylistTree(PlaylistTree):
    def context_menu(self, position: QPoint) -> QMenu:
        return self._build_context_menu(position)


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=(
                Playlist(1, "Travel", PlaylistKind.FOLDER),
                Playlist(2, "Long Drives", PlaylistKind.FOLDER, parent_id=1),
                Playlist(3, "Country Roads", parent_id=2),
                Playlist(4, "Favorites", PlaylistKind.SMART),
            )
        )
    )
    return workspace


def test_sidebar_selects_nested_playlist_and_preserves_it_after_a_move() -> None:
    workspace = _workspace()
    sidebar = PlaylistTree(workspace)
    selected: list[int] = []
    sidebar.selected.connect(selected.append)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    assert tree is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.select_playlist(3)
        assert selected == [3]
        assert sidebar.current_playlist_id == 3
        assert tree.isExpanded(model.index_for_id(1))
        assert tree.isExpanded(model.index_for_id(2))
        workspace.move(3, 1)
        assert sidebar.current_playlist_id == 3
        assert tree.currentIndex() == model.index_for_id(3)
        assert tree.isExpanded(model.index_for_id(1))
        workspace.load(workspace.snapshot)
        _assert_unselected(sidebar)
        assert not tree.currentIndex().isValid()
        assert not tree.isExpanded(model.index_for_id(1))
    finally:
        sidebar.close()


def test_add_menu_emits_all_three_creation_intents() -> None:
    sidebar = PlaylistTree(_workspace())
    requested: list[PlaylistKind] = []
    sidebar.createRequested.connect(requested.append)
    button = sidebar.findChild(QToolButton, "newPlaylistButton")
    assert button is not None
    menu = button.menu()
    try:
        assert not button.isHidden()
        assert button.isEnabled()
        assert [action.text() for action in menu.actions()] == [
            "New Playlist…",
            "New Smart Playlist…",
            "New Folder…",
        ]
        for action in menu.actions():
            action.trigger()
        assert requested == [
            PlaylistKind.PLAYLIST,
            PlaylistKind.SMART,
            PlaylistKind.FOLDER,
        ]
    finally:
        sidebar.close()


def test_accordion_icon_keeps_its_color_when_expanded_and_collapsed() -> None:
    sidebar = PlaylistTree(_workspace())
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert toggle is not None
    try:
        collapsed = toggle.icon().pixmap(toggle.iconSize()).toImage()
        toggle.click()
        assert toggle.isChecked()
        assert toggle.icon().pixmap(toggle.iconSize()).toImage() == collapsed
        toggle.click()
        assert not toggle.isChecked()
        assert toggle.icon().pixmap(toggle.iconSize()).toImage() == collapsed
    finally:
        sidebar.close()


def test_right_disclosure_expands_without_opening_a_folder_page() -> None:
    sidebar = PlaylistTree(_workspace())
    selected: list[int] = []
    sidebar.selected.connect(selected.append)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert tree is not None and toggle is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(240, 300)
        sidebar.show()
        toggle.click()
        APPLICATION.processEvents()
        folder = model.index_for_id(1)
        height = tree.height()
        row = tree.visualRect(folder)
        QTest.mouseClick(
            tree.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(row.right() - 16, row.center().y()),
        )
        APPLICATION.processEvents()
        assert tree.isExpanded(folder)
        assert tree.height() > height
        assert selected == []

        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=row.center())
        assert selected == [1]
        assert tree.isExpanded(folder)
        QTest.keyClick(tree, Qt.Key.Key_Left)
        assert not tree.isExpanded(folder)
        QTest.keyClick(tree, Qt.Key.Key_Right)
        assert tree.isExpanded(folder)

        nested = model.index_for_id(2)
        row = tree.visualRect(nested)
        QTest.mouseClick(
            tree.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(4, row.center().y()),
        )
        assert selected == [1, 2]
        assert not tree.isExpanded(nested)
        QTest.mouseClick(
            tree.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(row.right() - 16, row.center().y()),
        )
        assert tree.isExpanded(nested)
        assert selected == [1, 2]
    finally:
        sidebar.close()


def test_clicking_the_current_folder_toggles_its_expansion() -> None:
    sidebar = PlaylistTree(_workspace())
    selected: list[int] = []
    sidebar.selected.connect(selected.append)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    assert tree is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(240, 300)
        sidebar.show()
        sidebar.select_playlist(1)
        APPLICATION.processEvents()
        folder = model.index_for_id(1)
        row = tree.visualRect(folder)

        assert not tree.isExpanded(folder)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=row.center())
        assert tree.isExpanded(folder)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=row.center())
        assert not tree.isExpanded(folder)
        assert selected == [1]
    finally:
        sidebar.close()


def test_collapsing_the_section_preserves_selection_and_folder_expansion() -> None:
    workspace = _workspace()
    sidebar = PlaylistTree(workspace)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert tree is not None and toggle is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.select_playlist(3)
        assert toggle.isChecked()
        QTest.keyClick(toggle, Qt.Key.Key_Space)
        assert not toggle.isChecked()
        assert tree.isHidden()
        workspace.update(3, name="Renamed")
        assert not toggle.isChecked()
        assert sidebar.current_playlist_id == 3
        toggle.click()
        assert tree.isExpanded(model.index_for_id(1))
        assert tree.isExpanded(model.index_for_id(2))
        assert sidebar.current_playlist_id == 3
    finally:
        sidebar.close()


def test_track_drag_spring_opens_a_collapsed_playlist_folder() -> None:
    workspace = _workspace()
    sidebar = PlaylistTree(workspace)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert tree is not None and toggle is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(240, 300)
        sidebar.show()
        toggle.click()
        APPLICATION.processEvents()
        folder = model.index_for_id(1)
        assert not tree.isExpanded(folder)
        position = tree.visualRect(folder).center()
        data = TrackSelectionMimeData(workspace, (1,))

        tree.dragEnterEvent(_drag_enter(position, data))
        tree.dragMoveEvent(_drag_move(position, data))
        QTest.qWait(250)
        assert not tree.isExpanded(folder)
        QTest.qWait(300)
        assert tree.isExpanded(folder)
        tree.dragLeaveEvent(QDragLeaveEvent())
    finally:
        sidebar.close()


def test_queue_track_drag_drops_on_a_playlist_despite_its_move_proposal() -> None:
    tracks = (
        Track(1, "Current", "Artist", "Album", 1_000),
        Track(2, "Queued", "Artist", "Album", 1_000),
    )
    playlist = Playlist(10, "Destination")
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tracks=tracks, playlists=(playlist,)))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.enqueue(tracks[0])
    controller.enqueue(tracks[1])
    data = controller.queue_model.mimeData([controller.queue_model.index(0, 0)])
    sidebar = PlaylistTree(workspace)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    assert tree is not None
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert toggle is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(240, 300)
        sidebar.show()
        toggle.click()
        APPLICATION.processEvents()
        position = tree.visualRect(model.index_for_id(playlist.playlist_id)).center()
        drop = QDropEvent(
            QPointF(position),
            Qt.DropAction.MoveAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        tree.dropEvent(drop)

        updated = workspace.playlist(playlist.playlist_id)
        assert updated is not None and updated.track_ids == (tracks[1].track_id,)
    finally:
        sidebar.close()
        controller.shutdown()


def test_track_drag_spring_opens_the_collapsed_playlists_section() -> None:
    workspace = _workspace()
    sidebar = PlaylistTree(workspace)
    toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
    assert toggle is not None
    try:
        sidebar.resize(240, 300)
        sidebar.show()
        APPLICATION.processEvents()
        assert not toggle.isChecked()
        data = TrackSelectionMimeData(workspace, (1,))
        event = _drag_enter(toggle.rect().center(), data)

        APPLICATION.sendEvent(toggle, event)
        assert event.isAccepted()
        QTest.qWait(250)
        assert not toggle.isChecked()
        QTest.qWait(300)
        assert toggle.isChecked()
        APPLICATION.sendEvent(toggle, QDragLeaveEvent())
    finally:
        sidebar.close()


def test_long_playlist_lists_scroll_with_library_and_reveal_keyboard_selection() -> (
    None
):
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(playlists=tuple(Playlist(i, f"Mix {i}") for i in range(100)))
    )
    sidebar = Sidebar(playlists=workspace)
    sidebar.resize(256, 800)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    scroll = sidebar.findChild(QScrollArea, "sidebarScroll")
    assert tree is not None and scroll is not None and sidebar.playlist_tree is not None
    try:
        sidebar.show()
        APPLICATION.processEvents()
        sidebar.playlist_tree.select_playlist(99)
        APPLICATION.processEvents()
        point = tree.viewport().mapTo(
            scroll.viewport(), tree.visualRect(tree.currentIndex()).center()
        )
        assert scroll.viewport().rect().contains(point)
        assert not tree.verticalScrollBar().isVisible()
        assert scroll.verticalScrollBar().maximum() > 0

        QTest.keyClick(tree, Qt.Key.Key_Home)
        APPLICATION.processEvents()
        assert sidebar.playlist_tree.current_playlist_id == 0
        point = tree.viewport().mapTo(
            scroll.viewport(), tree.visualRect(tree.currentIndex()).center()
        )
        assert scroll.viewport().rect().contains(point)
    finally:
        sidebar.close()


def test_context_menu_edits_playlist_and_moves_it_to_top_level() -> None:
    workspace = _workspace()
    sidebar = _TestPlaylistTree(workspace)
    edited: list[int] = []
    removed: list[int] = []
    sidebar.editRequested.connect(edited.append)
    sidebar.removeRequested.connect(removed.append)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    assert tree is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(250, 360)
        sidebar.show()
        sidebar.select_playlist(3)
        APPLICATION.processEvents()
        position = tree.visualRect(model.index_for_id(3)).center()
        menu = sidebar.context_menu(position)
        assert [action.text() for action in menu.actions()] == [
            "Edit Playlist…",
            "Move to Top Level",
            "",
            "Remove Playlist…",
        ]
        menu.actions()[0].trigger()
        assert edited == [3]
        menu.actions()[1].trigger()
        assert not model.index_for_id(3).parent().isValid()
        assert sidebar.current_playlist_id == 3
        position = tree.visualRect(model.index_for_id(3)).center()
        sidebar.context_menu(position).actions()[-1].trigger()
        assert removed == [3]
        sidebar.clear_selection()
        _assert_unselected(sidebar)
    finally:
        sidebar.close()


def test_creation_is_disabled_without_an_active_library() -> None:
    workspace = LibraryWorkspace()
    sidebar = PlaylistTree(workspace)
    button = sidebar.findChild(QToolButton, "newPlaylistButton")
    assert button is not None
    try:
        assert not button.isEnabled()
        workspace.load(LibrarySnapshot())
        assert button.isEnabled()
        workspace.load(None)
        assert not button.isEnabled()
    finally:
        sidebar.close()


def test_open_context_menu_cannot_edit_another_active_library() -> None:
    workspace = _workspace()
    sidebar = _TestPlaylistTree(workspace)
    edited: list[int] = []
    sidebar.editRequested.connect(edited.append)
    tree = sidebar.findChild(QTreeView, "playlistTree")
    assert tree is not None
    model = tree.model()
    assert isinstance(model, PlaylistTreeModel)
    try:
        sidebar.resize(250, 360)
        sidebar.show()
        sidebar.select_playlist(3)
        APPLICATION.processEvents()
        menu = sidebar.context_menu(tree.visualRect(model.index_for_id(3)).center())
        workspace.load(workspace.snapshot)
        for action in menu.actions():
            action.trigger()
        assert edited == []
        assert model.index_for_id(3).parent() == model.index_for_id(2)
        assert not workspace.dirty
    finally:
        sidebar.close()


def _drag_enter(position: QPoint, data: TrackSelectionMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        position,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag_move(position: QPoint, data: TrackSelectionMimeData) -> QDragMoveEvent:
    return QDragMoveEvent(
        position,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
