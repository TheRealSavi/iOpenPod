"""Navigation style changes preserve the Library shell's current workflow."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStackedWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)

from iOpenPod.app.core.settings.definitions import (
    NAVIGATION_STYLE,
    PLAYER_POSITION,
    NavigationStyle,
    PlayerPosition,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.library import LibrarySnapshot, Playlist


@pytest.mark.parametrize("position", list(PlayerPosition))
def test_navigation_style_applies_immediately_and_keeps_current_page(
    position: PlayerPosition,
) -> None:
    context = build_context()
    context.settings.set_global(PLAYER_POSITION, position.value)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        sidebar = window.findChild(Sidebar)
        top_bar = window.findChild(CompactTopBar)
        combo = window.findChild(AppComboBox, "navigationStyleCombo")
        pages = window.findChild(QStackedWidget, "pageStack")
        player = window.findChild(PlayerBar)
        shell = window.findChild(QWidget, "appShell")
        assert sidebar is not None and top_bar is not None and combo is not None
        assert pages is not None and player is not None and shell is not None
        assert sidebar.isVisible() and not top_bar.isVisible()
        sidebar.pageRequested.emit(PageId.SETTINGS.value)
        current = pages.currentWidget()

        combo.setCurrentIndex(combo.findData(NavigationStyle.COMPACT_TOP_BAR.value))
        APPLICATION.processEvents()
        assert context.settings.get(NAVIGATION_STYLE) == "compact-top-bar"
        assert top_bar.isVisible() and not sidebar.isVisible()
        assert pages.currentWidget() is current
        assert top_bar.width() == shell.width()
        assert top_bar.height() < 60
        layout = shell.layout()
        assert layout is not None
        assert layout.indexOf(player) == (
            0 if position is PlayerPosition.TOP else layout.count() - 1
        )

        top_bar.pageRequested.emit(PageId.ARTISTS.value)
        assert pages.currentWidget() is not current
        current = pages.currentWidget()
        context.settings.reset_global(NAVIGATION_STYLE)
        assert sidebar.isVisible() and not top_bar.isVisible()
        assert pages.currentWidget() is current
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_compact_navigation_restores_on_startup_and_exits_during_sync() -> None:
    context = build_context()
    context.settings.set_global(NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        sidebar = window.findChild(Sidebar)
        top_bar = window.findChild(CompactTopBar)
        workspaces = window.findChild(QStackedWidget, "workspaceStack")
        assert sidebar is not None and top_bar is not None and workspaces is not None
        assert top_bar.isVisible() and not sidebar.isVisible()
        workspaces.setCurrentIndex(1)
        assert not top_bar.isVisible()
        context.settings.reset_global(NAVIGATION_STYLE)
        assert not top_bar.isVisible() and not sidebar.isVisible()
        context.settings.set_global(
            NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value
        )
        assert not top_bar.isVisible() and not sidebar.isVisible()
        workspaces.setCurrentIndex(0)
        assert top_bar.isVisible() and not sidebar.isVisible()
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_style_changed_during_fullscreen_is_applied_when_shell_returns() -> None:
    context = build_context()
    context.settings.set_global(NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        window.activateWindow()
        APPLICATION.processEvents()
        top_bar = window.findChild(CompactTopBar)
        sidebar = window.findChild(Sidebar)
        assert top_bar is not None and sidebar is not None
        top_bar.pageRequested.emit(PageId.SYNESTHESIA.value)
        APPLICATION.processEvents()
        QTest.keyClick(window, Qt.Key.Key_F11)
        APPLICATION.processEvents()
        assert window.isFullScreen()
        assert not top_bar.isVisible() and not sidebar.isVisible()
        context.settings.reset_global(NAVIGATION_STYLE)
        assert not top_bar.isVisible() and not sidebar.isVisible()
        QTest.keyClick(window, Qt.Key.Key_Escape)
        APPLICATION.processEvents()
        assert not window.isFullScreen()
        assert sidebar.isVisible() and not top_bar.isVisible()
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_both_navigation_styles_share_playlist_selection_without_resetting_page() -> (
    None
):
    context = build_context()
    context.library_workspace.load(
        LibrarySnapshot(playlists=(Playlist(1, "First"), Playlist(2, "Second")))
    )
    window = MainWindow(context, auto_discover=False)
    try:
        sidebar = window.findChild(Sidebar)
        top_bar = window.findChild(CompactTopBar)
        page = window.findChild(PlaylistPage, "playlistsPage")
        assert sidebar is not None and top_bar is not None and page is not None
        assert sidebar.playlist_tree is not None
        sidebar.playlist_tree.select_playlist(1)
        assert (
            page.selected_playlist_id,
            top_bar.playlist_tree.current_playlist_id,
        ) == (1, 1)

        context.settings.set_global(
            NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value
        )
        selected_after_switch = page.selected_playlist_id
        assert selected_after_switch == 1
        top_bar.playlist_tree.select_playlist(2)
        assert (
            page.selected_playlist_id,
            sidebar.playlist_tree.current_playlist_id,
        ) == (2, 2)

        top_bar.pageRequested.emit(PageId.TRACKS.value)
        assert page.selected_playlist_id is None
        assert top_bar.playlist_tree.current_playlist_id is None
        assert sidebar.playlist_tree.current_playlist_id is None
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
