import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QStackedWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
    tracks,
)
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.core.settings.definitions import WINDOW_GEOMETRY
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.pages.synesthesia_page import SynesthesiaPage
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import IconButton


def test_player_opens_synesthesia_without_a_sidebar_route_or_playback_interruption() -> (
    None
):
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        sidebar_routes = {
            button.property("pageId") for button in window.findChildren(QPushButton)
        }
        visualizer = window.findChild(IconButton, "playerVisualizer")
        assert PageId.SYNESTHESIA.value not in sidebar_routes
        assert visualizer is not None
        assert not visualizer.isEnabled()

        track = tracks(1)[0]
        context.playback_controller.enqueue(track)
        APPLICATION.processEvents()
        assert context.playback_controller.playing
        assert visualizer.isEnabled()
        assert visualizer.accessibleName() == "Open visualizer for current Track"
        assert visualizer.toolTip() == visualizer.accessibleName()
        transport_before = (
            tuple(backend.started_attempt_ids),
            backend.play_calls,
            backend.pause_calls,
            backend.stop_calls,
            tuple(backend.seeks),
        )

        visualizer.click()
        APPLICATION.processEvents()

        stack = window.findChild(QStackedWidget, "pageStack")
        assert stack is not None
        current = stack.currentWidget()
        assert current is not None
        assert current.objectName() == "synesthesiaPage"
        assert context.synesthesia_controller.track == track
        assert context.playback_controller.current_track == track
        assert context.playback_controller.playing

        synesthesia = window.findChild(SynesthesiaPage)
        assert synesthesia is not None
        synesthesia.renderer.failure.emit("test renderer failure")
        albums = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.ALBUMS.value
        )
        albums.click()
        APPLICATION.processEvents()
        assert (
            tuple(backend.started_attempt_ids),
            backend.play_calls,
            backend.pause_calls,
            backend.stop_calls,
            tuple(backend.seeks),
        ) == transport_before
        assert context.playback_controller.playing
    finally:
        window.close()
        window.deleteLater()
        APPLICATION.processEvents()
        context.shutdown()


@pytest.mark.parametrize("enter_key", [Qt.Key.Key_F, Qt.Key.Key_F11])
@pytest.mark.parametrize("exit_key", [Qt.Key.Key_F, Qt.Key.Key_F11, Qt.Key.Key_Escape])
@pytest.mark.parametrize("maximized", [False, True])
def test_visualizer_fullscreen_keys_fill_display_and_restore_shell(
    enter_key: Qt.Key, exit_key: Qt.Key, maximized: bool
) -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)
    try:
        if maximized:
            window.showMaximized()
        else:
            window.resize(960, 700)
            window.show()
        window.activateWindow()
        context.playback_controller.enqueue(tracks(1)[0])
        APPLICATION.processEvents()
        visualizer = window.findChild(IconButton, "playerVisualizer")
        assert visualizer is not None
        visualizer.click()
        APPLICATION.processEvents()
        page = window.findChild(SynesthesiaPage)
        assert page is not None
        if maximized:
            queue_toggle = window.findChild(IconButton, "playerQueueToggle")
            assert queue_toggle is not None
            queue_toggle.click()
            QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        renderer = page.renderer
        original_size = window.size()
        original_minimum = window.minimumSize()
        chrome = tuple(
            window.findChild(QWidget, name)
            for name in ("playerBar", "appSidebar", "playbackPaneHost", "appStatusBar")
        )
        assert all(widget is not None for widget in chrome)
        visible_before = tuple(widget.isVisible() for widget in chrome if widget)
        transport_before = (
            tuple(backend.started_attempt_ids),
            backend.play_calls,
            backend.pause_calls,
            backend.stop_calls,
            tuple(backend.seeks),
        )
        # Opening via the Player leaves focus outside the graphics page.
        visualizer.setFocus()
        QTest.keyClick(visualizer, enter_key)
        APPLICATION.processEvents()

        assert window.isFullScreen()
        assert all(not widget.isVisible() for widget in chrome if widget)
        assert page.renderer is renderer
        assert renderer.mapTo(window, QPoint()) == QPoint()
        assert renderer.size() == window.size()
        screen = window.screen()
        assert window.geometry() == screen.geometry()

        # Holding a toggle key must not immediately leave fullscreen.
        repeat = QKeyEvent(
            QEvent.Type.KeyPress, enter_key, Qt.KeyboardModifier.NoModifier, "", True
        )
        APPLICATION.sendEvent(window, repeat)
        assert window.isFullScreen()
        QTest.keyClick(window, exit_key)
        APPLICATION.processEvents()

        assert not window.isFullScreen()
        assert window.isMaximized() == maximized
        assert window.size() == original_size
        assert window.minimumSize() == original_minimum
        assert (
            tuple(widget.isVisible() for widget in chrome if widget) == visible_before
        )
        assert page.isVisible()
        assert page.renderer is renderer
        assert context.playback_controller.playing
        assert (
            tuple(backend.started_attempt_ids),
            backend.play_calls,
            backend.pause_calls,
            backend.stop_calls,
            tuple(backend.seeks),
        ) == transport_before
    finally:
        window.close()
        window.deleteLater()
        APPLICATION.processEvents()
        context.shutdown()


def test_fullscreen_shortcuts_only_enter_from_the_visible_visualizer() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        window.activateWindow()
        APPLICATION.processEvents()
        for key in (Qt.Key.Key_F, Qt.Key.Key_F11, Qt.Key.Key_Escape):
            QTest.keyClick(window, key)
            APPLICATION.processEvents()
            assert not window.isFullScreen()
        context.playback_controller.enqueue(tracks(1)[0])
        visualizer = window.findChild(IconButton, "playerVisualizer")
        assert visualizer is not None
        visualizer.click()
        APPLICATION.processEvents()
        QTest.keyClick(window, Qt.Key.Key_Escape)
        assert not window.isFullScreen()

        QTest.keyClick(window, Qt.Key.Key_F)
        APPLICATION.processEvents()
        assert window.isFullScreen()
        settings = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.SETTINGS.value
        )
        assert settings.isEnabled()
        settings.click()
        APPLICATION.processEvents()
        stack = window.findChild(QStackedWidget, "pageStack")
        assert stack is not None
        assert isinstance(stack.currentWidget(), SettingsPage)
        assert not window.isFullScreen()
        assert visualizer.isVisible()
        QTest.keyClick(window, Qt.Key.Key_F11)
        assert not window.isFullScreen()
    finally:
        window.close()
        window.deleteLater()
        APPLICATION.processEvents()
        context.shutdown()


def test_native_fullscreen_exit_restores_chrome_and_close_saves_normal_geometry() -> (
    None
):
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        window.activateWindow()
        context.playback_controller.enqueue(tracks(1)[0])
        APPLICATION.processEvents()
        visualizer = window.findChild(IconButton, "playerVisualizer")
        assert visualizer is not None
        visualizer.click()
        APPLICATION.processEvents()
        QTest.keyClick(window, Qt.Key.Key_F11)
        APPLICATION.processEvents()
        assert window.isFullScreen()

        window.showNormal()
        APPLICATION.processEvents()
        assert not window.isFullScreen()
        assert visualizer.isVisible()
        assert window.statusBar().isVisible()

        QTest.keyClick(window, Qt.Key.Key_F11)
        APPLICATION.processEvents()
        assert window.isFullScreen()
        window.close()
        restored = QWidget()
        assert restored.restoreGeometry(context.settings.get(WINDOW_GEOMETRY))
        assert not restored.isFullScreen()
    finally:
        window.deleteLater()
        APPLICATION.processEvents()
        context.shutdown()
