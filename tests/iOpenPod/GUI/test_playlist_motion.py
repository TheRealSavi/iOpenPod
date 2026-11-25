"""Playlist reveals animate their enclosing navigation without delaying intent."""

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import make_active_ipod
from tests.iOpenPod.GUI.motion_test_support import disable_motion

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.playlist_tree_model import PlaylistRole, PlaylistTreeModel
from iOpenPod.GUI.presentation.motion import MOTION
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=(
                Playlist(1, "Folder", PlaylistKind.FOLDER),
                *(Playlist(i, f"Playlist {i}", parent_id=1) for i in range(2, 10)),
                Playlist(10, "Following playlist"),
            )
        )
    )
    return workspace


def _animation(tree: PlaylistTree, name: str) -> QVariantAnimation:
    animation = tree.findChild(QVariantAnimation, name)
    assert animation is not None
    return animation


def _body(tree: PlaylistTree) -> QWidget:
    body = tree.findChild(QWidget, "playlistReveal")
    assert body is not None
    return body


def _open_playlist_popup(bar: CompactTopBar) -> QWidget:
    bar.resize(1200, bar.sizeHint().height())
    bar.show()
    bar.activateWindow()
    APPLICATION.processEvents()
    QTest.mouseMove(bar, QPoint(1, 1))
    button = bar.findChild(QPushButton, "compactPlaylists")
    assert button is not None
    QTest.keyClick(button, Qt.Key.Key_Down)
    popup = bar.findChild(QWidget, "compactPlaylistPopup")
    assert popup is not None
    return popup


def test_first_section_reveal_and_rapid_reversal_keep_current_height() -> None:
    tree = PlaylistTree(_workspace())
    tree.resize(240, 400)
    tree.show()
    APPLICATION.processEvents()
    try:
        toggle = tree.findChild(QPushButton, "playlistSectionToggle")
        assert toggle is not None
        animation = _animation(tree, "playlistSectionAnimation")
        body = _body(tree)
        toggle.click()
        assert animation.state() == QAbstractAnimation.State.Running
        assert body.height() == 0
        animation.setCurrentTime(32)
        height = body.height()
        assert 0 < height < animation.endValue()
        toggle.click()
        assert body.height() == height
        assert not toggle.isChecked()
        animation.setCurrentTime(animation.duration())
        assert body.isHidden() and body.height() == 0
        toggle.click()
        animation.setCurrentTime(animation.duration())
        assert body.isVisible() and body.height() > height
    finally:
        tree.close()


@pytest.mark.parametrize("dropdown", (False, True))
def test_folder_reveal_resizes_body_and_keeps_native_navigation(dropdown: bool) -> None:
    tree = PlaylistTree(_workspace(), show_heading=not dropdown)
    tree.select_playlist(1)
    tree.resize(240, 400)
    tree.show()
    APPLICATION.processEvents()
    try:
        view = tree.findChild(QTreeView, "playlistTree")
        assert view is not None and not view.isAnimated()
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        folder = model.index_for_id(1)
        animation = _animation(tree, "playlistFolderAnimation")
        body = _body(tree)
        collapsed = body.height()
        QTest.keyClick(view, Qt.Key.Key_Right)
        assert view.isExpanded(folder)
        assert animation.state() == QAbstractAnimation.State.Running
        assert body.height() == collapsed
        assert animation.duration() == MOTION.expand_ms
        animation.setCurrentTime(animation.duration() // 4)
        # Most of the movement happens promptly, with a restrained settling tail.
        progress = (body.height() - collapsed) / (animation.endValue() - collapsed)
        assert 0.65 < progress < 0.8
        assert collapsed < body.height() < animation.endValue()
        # The fixed folder row accepts a reversal during the branch slide.
        reversal_height = body.height()
        QTest.keyClick(view, Qt.Key.Key_Left)
        assert not view.isExpanded(folder)
        assert body.height() == reversal_height
        assert animation.duration() == MOTION.panel_exit_ms
        animation.setCurrentTime(animation.duration())
        assert body.height() == collapsed
        assert tree.current_playlist_id == 1
    finally:
        tree.close()


def test_popup_tracks_each_folder_frame_without_an_extra_scrollbar() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(make_active_ipod())
    try:
        popup = _open_playlist_popup(bar)
        view = popup.findChild(QTreeView, "playlistTree")
        scroll = popup.findChild(QScrollArea, "compactPlaylistScroll")
        assert view is not None and scroll is not None
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        animation = _animation(bar.playlist_tree, "playlistFolderAnimation")
        closed_height = popup.height()
        view.expand(model.index_for_id(1))
        assert popup.height() == closed_height
        animation.setCurrentTime(animation.duration() // 2)
        APPLICATION.processEvents()
        middle_height = popup.height()
        assert middle_height > closed_height
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        assert middle_height < popup.height() <= 420
        assert scroll.verticalScrollBar().maximum() == 0
        view.collapse(model.index_for_id(1))
        animation.setCurrentTime(animation.duration() // 2)
        assert closed_height < popup.height() < 420
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        assert popup.isVisible() and popup.height() == closed_height
        assert bar.playlist_tree.current_playlist_id is None
    finally:
        bar.close()


class _ColoredRows(QStyledItemDelegate):
    """Make rendered row positions measurable independently of the animation."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        playlist = index.data(PlaylistRole.PLAYLIST)
        assert isinstance(playlist, Playlist)
        color = (
            "#0000ff"
            if playlist.playlist_id == 1
            else "#00ff00"
            if playlist.playlist_id == 10
            else "#ff0000"
        )
        painter.fillRect(option.rect, QColor(color))

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(0, 32)


def test_rendered_rows_follow_the_body_clock_and_reverse_without_a_jump() -> None:
    tree = PlaylistTree(_workspace(), show_heading=False)
    view = tree.findChild(QTreeView, "playlistTree")
    assert view is not None
    view.setItemDelegate(_ColoredRows(view))
    tree.resize(240, 400)
    tree.show()
    APPLICATION.processEvents()
    try:
        folder = view.model().index(0, 0)
        view.setCurrentIndex(folder)
        animation = _animation(tree, "playlistFolderAnimation")
        row_height = view.visualRect(folder).height()
        view.expand(folder)
        for time in (0, 32, 70):
            animation.setCurrentTime(time)
            frame = view.viewport().grab().toImage()
            following_top = _body(tree).height() - row_height
            assert frame.pixelColor(12, following_top) == QColor("#00ff00")
            if time:
                assert frame.pixelColor(12, following_top - 1) == QColor("#ff0000")
        before_reversal = view.viewport().grab().toImage()
        height = _body(tree).height()
        view.collapse(folder)
        assert _body(tree).height() == height
        assert view.viewport().grab().toImage() == before_reversal
        # A redirect keeps forward momentum briefly instead of resetting speed.
        animation.setCurrentTime(1)
        assert animation.currentValue() > animation.startValue()
        for time in (32, 100, animation.duration()):
            animation.setCurrentTime(time)
            frame = view.viewport().grab().toImage()
            following_top = _body(tree).height() - row_height
            assert frame.pixelColor(12, following_top) == QColor("#00ff00")
        assert _body(tree).height() == 2 * row_height
    finally:
        tree.close()


def test_dropdown_folder_click_keeps_animating_when_selection_is_synchronized() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(make_active_ipod())
    tree = bar.playlist_tree
    # The application echoes a committed Playlist back to both navigation trees.
    tree.selected.connect(tree.select_playlist)
    try:
        popup = _open_playlist_popup(bar)
        view = popup.findChild(QTreeView, "playlistTree")
        assert view is not None
        folder = view.model().index(0, 0)
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(folder).center(),
        )
        animation = _animation(tree, "playlistFolderAnimation")
        assert popup.isVisible() and view.isExpanded(folder)
        assert tree.current_playlist_id == 1
        assert animation.state() == QAbstractAnimation.State.Running
        animation.setCurrentTime(animation.duration())
    finally:
        bar.close()


@pytest.mark.parametrize("interrupt", ("hide", "reload", "disabled", "disable_during"))
@pytest.mark.parametrize("folder", (False, True))
def test_interruption_settles_the_reveal_and_discards_old_rows(
    interrupt: str, folder: bool
) -> None:
    workspace = _workspace()
    tree = PlaylistTree(workspace)
    tree.resize(240, 400)
    tree.show()
    APPLICATION.processEvents()
    try:
        toggle = tree.findChild(QPushButton, "playlistSectionToggle")
        view = tree.findChild(QTreeView, "playlistTree")
        assert toggle is not None and view is not None
        if interrupt == "disabled":
            disable_motion(tree)
        toggle.click()
        animation = _animation(tree, "playlistSectionAnimation")
        if folder:
            animation.setCurrentTime(animation.duration())
            view.expand(view.model().index(0, 0))
            animation = _animation(tree, "playlistFolderAnimation")
            animation.setCurrentTime(32)
        if interrupt == "hide":
            tree.hide()
            tree.show()
        elif interrupt == "reload":
            workspace.load(LibrarySnapshot(playlists=(Playlist(20, "Replacement"),)))
        elif interrupt == "disable_during":
            disable_motion(tree)
        assert animation.state() == QAbstractAnimation.State.Stopped
        slide = view.findChild(QWidget, "playlistBranchSlide")
        assert slide is not None and slide.isHidden()
        assert (
            _body(tree).height()
            == tree.sizeHint().height() - toggle.sizeHint().height()
        )
        if interrupt == "disabled":
            assert not view.isAnimated()
            view.expand(view.model().index(0, 0))
            assert (
                _animation(tree, "playlistFolderAnimation").state()
                == QAbstractAnimation.State.Stopped
            )
    finally:
        tree.close()
