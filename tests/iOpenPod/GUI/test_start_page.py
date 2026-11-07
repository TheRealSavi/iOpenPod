"""The no-device entry point shares the shell's existing selection workflow."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget
from tests.iOpenPod.app.test_device_controller import (
    _device_root,  # pyright: ignore[reportPrivateUsage]
    _wait_until,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import NAVIGATION_STYLE, NavigationStyle
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.pages.start_page import StartPage
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from storage import Storage
from storage.testing import VirtualStoragePlatform


def _assert_library_navigation(window: MainWindow, *, connected: bool) -> None:
    sidebar = window.findChild(Sidebar)
    bar = window.findChild(CompactTopBar)
    assert sidebar is not None and bar is not None
    library_pages = (
        PageId.ALBUMS,
        PageId.ARTISTS,
        PageId.GENRES,
        PageId.TRACKS,
        PageId.PLAYLISTS,
        PageId.AUDIOBOOKS,
    )
    for navigation in (sidebar, bar):
        assert navigation.page_available(PageId.START) is not connected
        for page_id in library_pages:
            assert navigation.page_available(page_id) is connected
    for sidebar_button in sidebar.findChildren(QPushButton):
        page_id = sidebar_button.property("pageId")
        if page_id == PageId.START.value:
            assert sidebar_button.isHidden() is connected
        elif page_id in library_pages:
            assert sidebar_button.isHidden() is not connected
    assert sidebar.playlist_tree is not None
    assert sidebar.playlist_tree.isHidden() is not connected
    for name, visible in (
        ("compactWelcome", not connected),
        ("compactChooseDevice", not connected),
        ("compactSyncWithHost", connected),
        ("compactAudio", connected),
        ("compactPlaylists", connected),
    ):
        button = bar.findChild(QPushButton, name)
        assert button is not None
        assert button.isHidden() is not visible


@pytest.mark.parametrize("style", tuple(NavigationStyle))
def test_startup_opens_welcome_page_with_choose_device(
    style: NavigationStyle,
) -> None:
    context = build_context()
    context.settings.set_global(NAVIGATION_STYLE, style.value)
    window = MainWindow(context)
    try:
        window.resize(960, 620)
        window.show()
        APPLICATION.processEvents()
        stack = window.findChild(QStackedWidget, "pageStack")
        page = window.findChild(StartPage)
        choose = window.findChild(ActionButton, "startChooseDevice")
        picker = window.findChild(DevicePickerDialog)
        sidebar = window.findChild(Sidebar)
        assert stack is not None and page is not None and choose is not None
        assert picker is not None and sidebar is not None
        assert stack.currentWidget() is page
        _assert_library_navigation(window, connected=False)
        assert context.device_controller.active_ipod is None
        assert not picker.isVisible()
        assert choose.isVisible() and choose.isEnabled()
        assert choose.text() == "Choose Device"
        assert choose.kind is ActionButtonKind.PRIMARY
        assert page.rect().contains(choose.geometry())
        assert choose.height() >= 44

        QTest.mouseClick(choose, Qt.MouseButton.LeftButton)
        assert picker.isVisible()
        picker.reject()
        assert stack.currentWidget() is page
        choose.setFocus()
        QTest.keyClick(choose, Qt.Key.Key_Space)
        assert picker.isVisible()
        picker.reject()

        context.settings.set_global(
            NAVIGATION_STYLE,
            NavigationStyle.SIDEBAR.value
            if style is NavigationStyle.COMPACT_TOP_BAR
            else NavigationStyle.COMPACT_TOP_BAR.value,
        )
        assert stack.currentWidget() is page
        sidebar.pageRequested.emit(PageId.SETTINGS.value)
        assert stack.currentWidget() is not page
        assert isinstance(stack.currentWidget(), SettingsPage)
        navigation = (
            window.findChild(CompactTopBar)
            if style is NavigationStyle.SIDEBAR
            else sidebar
        )
        assert navigation is not None
        welcome = next(
            button
            for button in navigation.findChildren(QPushButton)
            if button.text() == "Welcome"
        )
        assert welcome.isVisible() and not welcome.isChecked()
        QTest.mouseClick(welcome, Qt.MouseButton.LeftButton)
        assert stack.currentWidget() is page
        assert welcome.isChecked()
    finally:
        window.close()
        context.shutdown()


def test_start_page_busy_state_and_language_change() -> None:
    page = StartPage()
    try:
        choose = page.findChild(ActionButton, "startChooseDevice")
        title = page.findChild(QLabel, "startTitle")
        assert choose is not None and title is not None
        requested = QSignalSpy(page.chooseDeviceRequested)
        page.set_busy(True)
        choose.click()
        assert not choose.isEnabled() and requested.count() == 0
        page.set_busy(False)
        choose.click()
        assert requested.count() == 1
        title.setText("Stale text")
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert title.text() == "Welcome to iOpenPod"
    finally:
        page.close()


def test_compact_choose_device_opens_picker_and_respects_busy_state() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        bar = window.findChild(CompactTopBar)
        picker = window.findChild(DevicePickerDialog)
        choose = window.findChild(ActionButton, "compactChooseDevice")
        assert bar is not None and picker is not None and choose is not None
        assert choose.isVisible() and choose.text() == "Choose Device"
        sync_requested = QSignalSpy(bar.syncRequested)
        bar.set_device_busy(True)
        choose.click()
        assert not choose.isEnabled() and not picker.isVisible()
        bar.set_device_busy(False)
        choose.setText("Stale text")
        APPLICATION.sendEvent(bar, QEvent(QEvent.Type.LanguageChange))
        assert choose.text() == "Choose Device"
        QTest.mouseClick(choose, Qt.MouseButton.LeftButton)
        assert picker.isVisible()
        assert sync_requested.count() == 0
        picker.reject()
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("style", tuple(NavigationStyle))
def test_selected_device_leaves_start_page_and_disconnect_returns(
    tmp_path: Path,
    style: NavigationStyle,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    context = build_context(device_coordinator=DeviceCoordinator(Storage(platform)))
    context.settings.set_global(NAVIGATION_STYLE, style.value)
    window = MainWindow(context, auto_discover=False)
    try:
        stack = window.findChild(QStackedWidget, "pageStack")
        page = window.findChild(StartPage)
        choose = window.findChild(ActionButton, "startChooseDevice")
        assert stack is not None and page is not None and choose is not None
        _assert_library_navigation(window, connected=False)
        controller = context.device_controller
        controller.refresh_devices()
        assert choose.isEnabled()  # Discovery leaves the picker available.
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        assert not choose.isEnabled()
        _wait_until(lambda: not controller.busy)
        loaded = controller.active_ipod
        assert loaded is not None
        assert stack.currentWidget() is not page
        assert isinstance(stack.currentWidget(), LibraryPage)
        _assert_library_navigation(window, connected=True)
        platform.disconnect(root)
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        assert controller.active_ipod is None
        assert stack.currentWidget() is page
        assert choose.isEnabled()
        _assert_library_navigation(window, connected=False)
    finally:
        window.close()
        context.shutdown()
