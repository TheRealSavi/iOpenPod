"""Compact navigation preserves Library actions and real Playlist drop targets."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import (
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QTreeView,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind, Track
from storage import FileFingerprint


def _active_ipod() -> ActiveIPod:
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("compact-test"),
        display_name="Test iPod",
        host_description="USB iPod",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=80_000_000_000,
        available_bytes=40_000_000_000,
    )
    return ActiveIPod(
        candidate=candidate,
        profile=profile,
        library=LibrarySnapshot(),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=0, modified_ns=0, device=0, inode=0, sha256="0" * 64
        ),
    )


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            tracks=(Track(10, "Song", "Artist", "Album", 1000),),
            playlists=(
                Playlist(1, "Travel", PlaylistKind.FOLDER),
                Playlist(2, "Roads", parent_id=1),
                Playlist(3, "Smart", PlaylistKind.SMART),
            ),
        )
    )
    return workspace


def _button(bar: CompactTopBar, name: str) -> QPushButton:
    button = bar.findChild(QPushButton, name)
    assert button is not None
    return button


def _popup(bar: CompactTopBar) -> QFrame:
    popup = bar.findChild(QFrame, "compactPlaylistPopup")
    assert popup is not None
    return popup


def test_compact_menus_route_the_requested_sections_and_actions() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[str] = []
    synced: list[bool] = []
    scrobbled: list[bool] = []
    bar.pageRequested.connect(requested.append)
    bar.syncRequested.connect(lambda: synced.append(True))
    bar.scrobbleRequested.connect(lambda: scrobbled.append(True))
    try:
        for name, expected in (
            (
                "compactAudio",
                [
                    "Albums",
                    "Artists",
                    "Genres",
                    "Tracks",
                    "Genius",
                    "Podcasts",
                    "Audiobooks",
                ],
            ),
            ("compactVideo", ["Movies", "TV Shows", "Music Videos", "Videos"]),
        ):
            menu = _button(bar, name).menu()
            assert [action.text() for action in menu.actions()] == expected
            for action in menu.actions():
                action.trigger()
                assert requested[-1] == action.data()
        menu = _button(bar, "compactMaintenance").menu()
        assert [action.text() for action in menu.actions() if action.isVisible()] == [
            "Backups",
            "Normalize Tags",
            "Scrobble Now",
        ]
        assert not menu.actions()[2].isEnabled()
        bar.set_scrobble_available(True)
        menu.actions()[2].trigger()
        assert scrobbled == [True]
        for name, page in (
            ("compactDeviceSummary", PageId.DEVICE_SUMMARY),
            ("compactPhotos", PageId.PHOTOS),
            ("compactGames", PageId.GAMES),
            ("compactSettings", PageId.SETTINGS),
        ):
            _button(bar, name).click()
            assert requested[-1] == page.value
        _button(bar, "compactSyncWithHost").click()
        assert synced == [True]
        bar.set_current_page(PageId.TRACKS)
        assert _button(bar, "compactAudio").isChecked()
        assert not _button(bar, "compactVideo").isChecked()
        bar.set_review_visible(True)
        bar.set_review_available(True)
        assert menu.actions()[-1].isVisible() and menu.actions()[-1].isEnabled()
    finally:
        bar.close()


def test_compact_bar_keeps_device_capability_and_availability_gates() -> None:
    bar = CompactTopBar(playlists=_workspace())
    choose: list[bool] = []
    bar.chooseDeviceRequested.connect(lambda: choose.append(True))
    try:
        assert not _button(bar, "compactSyncWithHost").isEnabled()
        _button(bar, "compactDeviceSummary").click()
        assert choose == [True]
        bar.set_device_busy(True)
        assert not _button(bar, "compactDeviceSummary").isEnabled()
        active = _active_ipod()
        profile = next(
            profile
            for profile in DEFAULT_DEVICE_REGISTRY.profiles
            if not profile.capabilities.video.supported
            and not profile.capabilities.artwork.supports_photos
            and not profile.capabilities.supports_games
        )
        bar.set_active_ipod(replace(active, profile=profile))
        assert _button(bar, "compactVideo").isHidden()
        assert _button(bar, "compactPhotos").isHidden()
        assert _button(bar, "compactGames").isHidden()
        assert not bar.page_available(PageId.MOVIES)
        assert _button(bar, "compactSyncWithHost").isEnabled()
    finally:
        bar.close()


def test_compact_navigation_is_centered_in_a_thin_strip() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        APPLICATION.processEvents()
        center = bar.findChild(QWidget, "compactNavigation")
        assert center is not None
        assert abs(center.geometry().center().x() - bar.rect().center().x()) <= 1
        assert bar.height() < 60
    finally:
        bar.close()


def test_device_actions_are_available_from_the_keyboard() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    choose: list[bool] = []
    eject: list[bool] = []
    bar.chooseDeviceRequested.connect(lambda: choose.append(True))
    bar.ejectRequested.connect(lambda: eject.append(True))
    try:
        bar.show()
        device = _button(bar, "compactDeviceSummary")
        device.setFocus()
        QTest.keyClick(device, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
        menu = device.findChild(QMenu)
        assert menu is not None and menu.isVisible()
        assert [action.text() for action in menu.actions()] == [
            "Eject",
            "Choose Device",
        ]
        assert not menu.actions()[0].isEnabled()
        menu.actions()[1].trigger()
        assert choose == [True]
        menu.hide()
        bar.set_eject_available(True)
        QTest.keyClick(device, Qt.Key.Key_Menu)
        assert menu.isVisible() and menu.actions()[0].isEnabled()
        menu.actions()[0].trigger()
        assert eject == [True]
    finally:
        bar.close()


def test_cancelled_menu_and_outside_click_preserve_current_navigation() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    bar.set_current_page(PageId.TRACKS)
    try:
        bar.show()
        for name in ("compactAudio", "compactVideo"):
            button = _button(bar, name)
            QTest.mouseMove(button, button.rect().center())
            assert button.menu().isVisible()
            QTest.keyClick(button.menu(), Qt.Key.Key_Escape)
            assert _button(bar, "compactAudio").isChecked()
            assert not _button(bar, "compactVideo").isChecked()
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Space)
        assert _popup(bar).isVisible()
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
        assert not _popup(bar).isVisible()
    finally:
        bar.close()


def _hover_device(bar: CompactTopBar) -> QFrame:
    QTest.mouseMove(bar, QPoint(bar.width() // 2, bar.height() - 1))
    device = _button(bar, "compactDeviceSummary")
    QTest.mouseMove(device, device.rect().center())
    APPLICATION.processEvents()
    menu = bar.findChild(QFrame, "compactDeviceHoverMenu")
    assert menu is not None and menu.isVisible()
    return menu


_DROPDOWNS = (
    "compactAudio",
    "compactVideo",
    "compactPlaylists",
    "compactMaintenance",
)


def _dropdown(bar: CompactTopBar, name: str) -> QWidget:
    return _popup(bar) if name == "compactPlaylists" else _button(bar, name).menu()


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize("opened", [False, True])
def test_dropdown_heading_clicks_do_nothing(name: str, opened: bool) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    bar.set_current_page(PageId.TRACKS)
    requested: list[str] = []
    clicked: list[bool] = []
    bar.pageRequested.connect(requested.append)
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        button = _button(bar, name)
        button.clicked.connect(clicked.append)
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        assert popup.isVisible()
        if not opened:
            QTest.keyClick(popup, Qt.Key.Key_Escape)
            assert not popup.isVisible()
        checked = [_button(bar, item).isChecked() for item in _DROPDOWNS]
        receivers = (button, popup) if opened else (button,)
        for receiver in receivers:
            position = receiver.mapFromGlobal(
                button.mapToGlobal(button.rect().center())
            )
            for mouse_button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                QTest.mousePress(receiver, mouse_button, pos=position)
                assert not button.isDown()
                QTest.mouseRelease(receiver, mouse_button, pos=position)
                QTest.mouseDClick(receiver, mouse_button, pos=position)
                QTest.mouseRelease(receiver, mouse_button, pos=position)
                APPLICATION.processEvents()
                assert popup.isVisible() is opened
                assert [
                    _button(bar, item).isChecked() for item in _DROPDOWNS
                ] == checked
                assert requested == [] and clicked == []
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
def test_navigation_dropdown_opens_on_hover_and_keeps_items_reachable(
    name: str,
) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[str] = []
    bar.pageRequested.connect(requested.append)
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        button = _button(bar, name)
        QTest.mouseMove(button, button.rect().center())
        APPLICATION.processEvents()
        popup = _dropdown(bar, name)
        assert popup.isVisible() and requested == []
        assert _button(bar, "compactAudio").isChecked()
        if isinstance(popup, QMenu):
            action = popup.actions()[0]
            point = popup.actionGeometry(action).center()
            QTest.mouseMove(popup, point)
            QTest.qWait(220)
            assert popup.isVisible()
            QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=point)
            assert requested == [action.data()]
            assert not popup.isVisible()
        else:
            view = popup.findChild(QTreeView, "playlistTree")
            assert view is not None
            QTest.mouseMove(view.viewport(), view.viewport().rect().center())
            QTest.qWait(220)
            assert popup.isVisible()
    finally:
        bar.close()


def test_hover_switches_between_dropdowns_while_a_popup_owns_mouse_events() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        audio = _button(bar, "compactAudio")
        QTest.mouseMove(audio, audio.rect().center())
        previous = _dropdown(bar, "compactAudio")
        assert previous.isVisible()
        for name in (*_DROPDOWNS[1:], "compactAudio"):
            button = _button(bar, name)
            # Qt delivers outside-pointer events to the open popup, not the bar.
            position = previous.mapFromGlobal(
                button.mapToGlobal(button.rect().center())
            )
            QTest.mouseMove(previous, position)
            APPLICATION.processEvents()
            popup = _dropdown(bar, name)
            assert popup.isVisible() and not previous.isVisible()
            previous = popup
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize("dismiss", ["leave", "escape", "hide", "disconnect"])
def test_hover_navigation_menus_dismiss_without_reopening(
    name: str, dismiss: str
) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        button = _button(bar, name)
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        assert popup.isVisible()
        if dismiss == "leave":
            QTest.mouseMove(popup, popup.mapFromGlobal(bar.mapToGlobal(QPoint(1, 1))))
        elif dismiss == "escape":
            QTest.keyClick(popup, Qt.Key.Key_Escape)
        elif dismiss == "hide":
            bar.hide()
        else:
            bar.set_active_ipod(None)
        APPLICATION.processEvents()
        QTest.qWait(220)
        assert not popup.isVisible()
    finally:
        bar.close()


def test_hover_playlist_menu_keeps_its_new_submenu_open() -> None:
    bar = CompactTopBar(playlists=_workspace())
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        button = _button(bar, "compactPlaylists")
        QTest.mouseMove(button, button.rect().center())
        popup = _popup(bar)
        new = _button(bar, "compactNewPlaylist")
        new.menu().popup(popup.mapToGlobal(QPoint(popup.width(), 0)))
        QTest.mouseMove(new.menu(), new.menu().rect().bottomRight() - QPoint(3, 3))
        QTest.qWait(220)
        assert new.menu().isVisible() and popup.isVisible()
        QTest.keyClick(new.menu(), Qt.Key.Key_Escape)
        assert not new.menu().isVisible() and popup.isVisible()
        new.menu().popup(new.mapToGlobal(QPoint(0, new.height())))
        audio = _button(bar, "compactAudio")
        point = new.menu().mapFromGlobal(audio.mapToGlobal(audio.rect().center()))
        QTest.mouseMove(new.menu(), point)
        assert audio.menu().isVisible()
        assert not popup.isVisible() and not new.menu().isVisible()
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
def test_keyboard_dropdown_stays_open_with_the_pointer_elsewhere(name: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    visible: list[bool] = []
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        QTest.mouseMove(bar, QPoint(1, 1))
        button = _button(bar, name)
        popup = _dropdown(bar, name)
        button.setFocus()

        def check_and_close() -> None:
            visible.append(popup.isVisible())
            popup.hide()

        QTimer.singleShot(260, bar, check_and_close)
        QTest.keyClick(button, Qt.Key.Key_Space)
        QTest.qWait(280)
        assert visible == [True]
    finally:
        bar.close()


def test_normal_hover_never_interrupts_a_playlist_drag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        button = _button(bar, "compactPlaylists")
        data = TrackSelectionMimeData(workspace, (10,))
        APPLICATION.sendEvent(button, _enter(button.rect().center(), data))
        QTest.qWait(550)
        popup = _popup(bar)
        assert popup.isVisible() and popup.windowType() == Qt.WindowType.Tool
        for name in _DROPDOWNS:
            target = _button(bar, name)
            QTest.mouseMove(target, target.rect().center())
            QTest.qWait(220)
            assert popup.isVisible() and popup.windowType() == Qt.WindowType.Tool
            assert all(
                not _dropdown(bar, other).isVisible()
                for other in _DROPDOWNS
                if other != "compactPlaylists"
            )
    finally:
        bar.close()


def test_device_hover_keeps_direct_image_click_available() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[str] = []
    bar.pageRequested.connect(requested.append)
    try:
        bar.resize(960, bar.sizeHint().height())
        bar.show()
        menu = _hover_device(bar)
        assert QApplication.activePopupWidget() is None
        assert QWidget.mouseGrabber() is None
        assert requested == []
        device = _button(bar, "compactDeviceSummary")
        QTest.mouseClick(device, Qt.MouseButton.LeftButton)
        assert requested == [PageId.DEVICE_SUMMARY.value]
        assert not menu.isVisible()
    finally:
        bar.close()


def test_device_hover_actions_keep_gates_and_are_reachable() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[str] = []
    bar.ejectRequested.connect(lambda: requested.append("eject"))
    bar.chooseDeviceRequested.connect(lambda: requested.append("choose"))
    try:
        bar.resize(960, bar.sizeHint().height())
        bar.show()
        menu = _hover_device(bar)
        eject, choose = menu.findChildren(QToolButton)
        assert [eject.text(), choose.text()] == ["Eject", "Choose Device"]
        assert not eject.isEnabled() and choose.isEnabled()
        bar.set_eject_available(True)
        QTest.mouseMove(eject, eject.rect().center())
        QTest.qWait(220)
        assert menu.isVisible() and eject.isEnabled()
        QTest.mouseClick(eject, Qt.MouseButton.LeftButton)
        assert requested == ["eject"] and not menu.isVisible()
        _hover_device(bar)
        QTest.mouseClick(choose, Qt.MouseButton.LeftButton)
        assert requested == ["eject", "choose"] and not menu.isVisible()
        _hover_device(bar)
        bar.set_device_busy(True)
        assert not choose.isEnabled()
        QTest.mouseClick(choose, Qt.MouseButton.LeftButton)
        assert requested == ["eject", "choose"]
    finally:
        bar.close()


@pytest.mark.parametrize(
    "dismiss",
    ["leave", "escape", "outside", "hide", "move", "disconnect", "deactivate"],
)
def test_device_hover_menu_dismisses_with_its_context(dismiss: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        bar.resize(960, bar.sizeHint().height())
        bar.show()
        menu = _hover_device(bar)
        if dismiss == "leave":
            QTest.mouseMove(bar, QPoint(bar.width() // 2, bar.height() - 1))
            QTest.qWait(220)
        elif dismiss == "escape":
            QTest.keyClick(bar, Qt.Key.Key_Escape)
        elif dismiss == "outside":
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
        elif dismiss == "hide":
            bar.hide()
        elif dismiss == "move":
            bar.move(bar.pos() + QPoint(10, 10))
        elif dismiss == "disconnect":
            bar.set_active_ipod(None)
        else:
            APPLICATION.sendEvent(bar, QEvent(QEvent.Type.ApplicationDeactivate))
        assert not menu.isVisible()
    finally:
        bar.close()


def test_playlist_popup_keeps_creation_folder_browsing_and_bounded_scrolling() -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    created: list[PlaylistKind] = []
    bar.playlist_tree.createRequested.connect(created.append)
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        _button(bar, "compactPlaylists").click()
        APPLICATION.processEvents()
        popup = _popup(bar)
        view = popup.findChild(QTreeView, "playlistTree")
        assert view is not None and popup.isVisible()
        assert popup.height() < 200
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        toggle = popup.findChild(QPushButton, "playlistSectionToggle")
        assert toggle is not None and toggle.isHidden()
        new = _button(bar, "compactNewPlaylist")
        assert new.text() == "New" and new.isEnabled()
        assert len(new.menu().actions()) == 3
        # A folder click selects its page but leaves the menu available to expand.
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(model.index_for_id(1)).center(),
        )
        assert popup.isVisible()
        # Programmatic selection from the shell does not dismiss the popup.
        bar.playlist_tree.select_playlist(2)
        assert popup.isVisible()
        QTest.keyClick(view, Qt.Key.Key_Return)
        assert not popup.isVisible()
        _button(bar, "compactPlaylists").click()
        new.menu().actions()[0].trigger()
        assert created == [PlaylistKind.PLAYLIST]
        assert not popup.isVisible()
        workspace.load(
            LibrarySnapshot(
                playlists=tuple(Playlist(i, f"Mix {i}") for i in range(100))
            )
        )
        _button(bar, "compactPlaylists").click()
        APPLICATION.processEvents()
        bar.playlist_tree.select_playlist(99)
        APPLICATION.processEvents()
        scroll = popup.findChild(QScrollArea, "compactPlaylistScroll")
        assert scroll is not None and scroll.verticalScrollBar().maximum() > 0
        point = view.viewport().mapTo(
            scroll.viewport(), view.visualRect(view.currentIndex()).center()
        )
        assert scroll.viewport().rect().contains(point)
        assert popup.height() <= 420
        QTest.keyClick(view, Qt.Key.Key_Escape)
        assert not popup.isVisible()
        _button(bar, "compactPlaylists").click()
        workspace.set_locked(True)
        assert not new.isEnabled()
    finally:
        bar.close()


def _enter(position: QPoint, data: TrackSelectionMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        position,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_drag_hover_opens_menu_expands_folder_and_drops_into_shared_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    data = TrackSelectionMimeData(workspace, (10,))
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        button = _button(bar, "compactPlaylists")
        event = _enter(button.rect().center(), data)
        APPLICATION.sendEvent(button, event)
        assert event.isAccepted()
        QTest.qWait(250)
        assert not _popup(bar).isVisible()
        QTest.qWait(300)
        popup = _popup(bar)
        assert popup.isVisible()
        assert popup.windowType() == Qt.WindowType.Tool
        view = popup.findChild(QTreeView, "playlistTree")
        assert view is not None
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        position = view.visualRect(model.index_for_id(1)).center()
        APPLICATION.sendEvent(view.viewport(), _enter(position, data))
        move = QDragMoveEvent(
            position,
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(view.viewport(), move)
        QTest.qWait(550)
        assert popup.isVisible() and view.isExpanded(model.index_for_id(1))
        position = view.visualRect(model.index_for_id(2)).center()
        drop = QDropEvent(
            QPointF(position),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(view.viewport(), drop)
        APPLICATION.processEvents()
        playlist = workspace.playlist(2)
        assert playlist is not None and playlist.track_ids == (10,)
        assert drop.isAccepted() and not popup.isVisible()
    finally:
        bar.close()


@pytest.mark.parametrize("invalid", ["foreign", "stale", "locked", "leave"])
def test_invalid_or_abandoned_drag_never_opens_the_popup(invalid: str) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    data = TrackSelectionMimeData(
        _workspace() if invalid == "foreign" else workspace, (10,)
    )
    try:
        bar.show()
        if invalid == "stale":
            workspace.load(workspace.snapshot)
        elif invalid == "locked":
            workspace.set_locked(True)
        button = _button(bar, "compactPlaylists")
        event = _enter(button.rect().center(), data)
        APPLICATION.sendEvent(button, event)
        if invalid == "leave":
            assert event.isAccepted()
            APPLICATION.sendEvent(button, QDragLeaveEvent())
        else:
            assert not event.isAccepted()
        QTest.qWait(550)
        assert not _popup(bar).isVisible()
    finally:
        bar.close()


def test_open_drag_popup_closes_after_cancel_or_library_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    held = True
    monkeypatch.setattr(
        QApplication,
        "mouseButtons",
        lambda: Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
    )
    try:
        bar.show()
        button = _button(bar, "compactPlaylists")
        data = TrackSelectionMimeData(workspace, (10,))
        APPLICATION.sendEvent(button, _enter(button.rect().center(), data))
        QTest.qWait(550)
        assert _popup(bar).isVisible()
        held = False
        QTest.qWait(150)
        assert not _popup(bar).isVisible()
        held = True
        APPLICATION.sendEvent(button, QDragLeaveEvent())
        APPLICATION.sendEvent(button, _enter(button.rect().center(), data))
        QTest.qWait(550)
        assert _popup(bar).isVisible()
        workspace.load(None)
        assert not _popup(bar).isVisible()
    finally:
        bar.close()


def test_drag_scrolls_at_popup_edge_to_reach_a_lower_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    workspace.load(
        LibrarySnapshot(
            tracks=workspace.snapshot.tracks if workspace.snapshot is not None else (),
            playlists=tuple(Playlist(i, f"Mix {i}") for i in range(100)),
        )
    )
    bar = CompactTopBar(playlists=workspace)
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    data = TrackSelectionMimeData(workspace, (10,))
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        button = _button(bar, "compactPlaylists")
        APPLICATION.sendEvent(button, _enter(button.rect().center(), data))
        QTest.qWait(550)
        popup = _popup(bar)
        view = popup.findChild(QTreeView, "playlistTree")
        scroll = popup.findChild(QScrollArea, "compactPlaylistScroll")
        assert view is not None and scroll is not None
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        target = model.index_for_id(15)
        point = view.viewport().mapTo(
            scroll.viewport(), view.visualRect(target).center()
        )
        assert not scroll.viewport().rect().contains(point)
        cursor = scroll.viewport().mapToGlobal(
            QPoint(
                scroll.viewport().width() // 2,
                scroll.viewport().height() - 1,
            )
        )
        monkeypatch.setattr(QCursor, "pos", lambda: cursor)
        QTest.qWait(650)
        assert scroll.verticalScrollBar().value() > 0
        point = view.viewport().mapTo(
            scroll.viewport(), view.visualRect(target).center()
        )
        assert scroll.viewport().rect().contains(point)
        cursor = scroll.viewport().mapToGlobal(QPoint(-5, -5))
        previous_scroll = scroll.verticalScrollBar().value()
        QTest.qWait(150)
        assert scroll.verticalScrollBar().value() == previous_scroll
        position = view.visualRect(target).center()
        APPLICATION.sendEvent(view.viewport(), _enter(position, data))
        drop = QDropEvent(
            QPointF(position),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(view.viewport(), drop)
        APPLICATION.processEvents()
        playlist = workspace.playlist(15)
        assert (
            drop.isAccepted() and playlist is not None and playlist.track_ids == (10,)
        )
        assert not popup.isVisible()
    finally:
        bar.close()


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
def test_small_themed_popup_has_no_unnecessary_scrollbar(mode: AppearanceMode) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    theme.set_mode(mode)
    bar = CompactTopBar(playlists=_workspace(), theme=theme)
    try:
        bar.show()
        _button(bar, "compactPlaylists").click()
        APPLICATION.processEvents()
        popup = _popup(bar)
        scroll = popup.findChild(QScrollArea, "compactPlaylistScroll")
        assert scroll is not None
        assert scroll.verticalScrollBar().maximum() == 0
        bar.playlist_tree.select_playlist(2)
        APPLICATION.processEvents()
        assert scroll.verticalScrollBar().maximum() == 0
        assert popup.height() < 200
    finally:
        bar.close()
        theme.close()
