"""Compact navigation preserves Library actions and real Playlist drop targets."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTranslator
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
    QListWidget,
    QPushButton,
    QScrollArea,
    QStyle,
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
from iOpenPod.GUI.widgets.hover_dropdown import HoverDropdown
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


def _hover_playlists(bar: CompactTopBar) -> None:
    QTest.mouseMove(bar, QPoint(1, 1))
    button = _button(bar, "compactPlaylists")
    QTest.mouseMove(button, button.rect().center())
    APPLICATION.processEvents()


_DROPDOWNS = (
    "compactDeviceSummary",
    "compactAudio",
    "compactVideo",
    "compactPlaylists",
    "compactMaintenance",
)


def _dropdown(bar: CompactTopBar, name: str) -> HoverDropdown:
    popup = _button(bar, name).findChild(HoverDropdown)
    assert popup is not None
    return popup


def _show(bar: CompactTopBar) -> None:
    bar.resize(1200, bar.sizeHint().height())
    bar.show()
    bar.activateWindow()
    APPLICATION.processEvents()
    QTest.mouseMove(bar, QPoint(1, 1))
    for name in _DROPDOWNS:
        _dropdown(bar, name).hide()


def test_compact_navigation_is_centered_in_a_thin_strip() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        center = bar.findChild(QWidget, "compactNavigation")
        assert center is not None
        assert abs(center.geometry().center().x() - bar.rect().center().x()) <= 1
        assert bar.height() < 60
    finally:
        bar.close()


@pytest.mark.parametrize(
    "language,device_label", [("de", "Gerät"), ("es", "Dispositivo")]
)
def test_dropdown_accessibility_retranslates_without_changing_selection(
    language: str, device_label: str
) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    assert translator.load(str(catalog))
    original = _button(bar, "compactAudio").accessibleDescription()
    bar.playlist_tree.select_playlist(3)
    try:
        APPLICATION.installTranslator(translator)
        APPLICATION.sendEvent(bar, QEvent(QEvent.Type.LanguageChange))
        assert _button(bar, "compactDeviceSummary").accessibleName() == device_label
        descriptions = {
            _button(bar, name).accessibleDescription() for name in _DROPDOWNS
        }
        assert len(descriptions) == 1 and original not in descriptions
        assert bar.playlist_tree.current_playlist_id == 3
    finally:
        APPLICATION.removeTranslator(translator)
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
def test_all_dropdowns_share_hover_without_activation(name: str) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    requested: list[object] = []
    bar.pageRequested.connect(requested.append)
    bar.playlist_tree.selected.connect(requested.append)
    try:
        _show(bar)
        workspace.load(workspace.snapshot)
        button = _button(bar, name)
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        assert popup.isVisible()
        assert button.property("dropdownOpen") is True
        assert not button.isChecked()
        assert requested == []
        QTest.mouseMove(popup, popup.mapFromGlobal(bar.mapToGlobal(QPoint(1, 1))))
        QTest.qWait(220)
        assert not popup.isVisible()
        assert button.property("dropdownOpen") is False
        assert button.property("dropdownHovered") is False
        assert not button.underMouse()
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Space, Qt.Key.Key_Down])
def test_keyboard_opens_and_highlights_without_invoking(name: str, key: Qt.Key) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[object] = []
    bar.pageRequested.connect(requested.append)
    bar.playlist_tree.selected.connect(requested.append)
    try:
        _show(bar)
        button = _button(bar, name)
        button.setFocus()
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
        QTest.keyClick(button, key)
        popup = _dropdown(bar, name)
        assert popup.isVisible() and requested == []
        first = next(
            row
            for row in popup.findChildren(QToolButton)
            if row.property("dropdownItem") and row.isVisible() and row.isEnabled()
        )
        assert popup.focusWidget() is first
        assert first.property("dropdownActive") is True
        QTest.keyClick(first, Qt.Key.Key_Escape)
        assert not popup.isVisible()
        assert button.hasFocus()
        assert requested == []
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
def test_clicking_heading_opens_first_item_without_invoking(name: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[object] = []
    bar.pageRequested.connect(requested.append)
    bar.playlist_tree.selected.connect(requested.append)
    try:
        _show(bar)
        button = _button(bar, name)
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        # Real popups receive heading clicks after grabbing the pointer.
        point = popup.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=point)
        assert popup.isVisible() and requested == []
        assert isinstance(popup.focusWidget(), QToolButton)
        assert popup.focusWidget().property("dropdownActive") is True
    finally:
        bar.close()


@pytest.mark.parametrize("name", [n for n in _DROPDOWNS if n != "compactPlaylists"])
def test_action_navigation_skips_disabled_and_only_enter_activates(name: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[object] = []
    bar.pageRequested.connect(requested.append)
    bar.chooseDeviceRequested.connect(lambda: requested.append("choose"))
    try:
        _show(bar)
        button = _button(bar, name)
        QTest.keyClick(button, Qt.Key.Key_Down)
        popup = _dropdown(bar, name)
        enabled = [a for a in popup.actions() if a.isVisible() and a.isEnabled()]
        assert len(enabled) >= 2
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Down)
        focused = popup.focusWidget()
        assert (
            isinstance(focused, QToolButton) and focused.defaultAction() is enabled[1]
        )
        assert requested == []
        QTest.keyClick(focused, Qt.Key.Key_Up)
        assert requested == []
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Return)
        assert len(requested) == 1
        assert not popup.isVisible()
    finally:
        bar.close()


def test_playlist_keyboard_highlight_is_not_library_selection() -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    selected: list[object] = []
    bar.playlist_tree.selected.connect(selected.append)
    try:
        _show(bar)
        workspace.load(workspace.snapshot)
        button = _button(bar, "compactPlaylists")
        QTest.keyClick(button, Qt.Key.Key_Down)
        popup = _dropdown(bar, "compactPlaylists")
        view = popup.findChild(QTreeView, "playlistTree")
        assert view is not None
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        # New, then the first Playlist Folder, then its child.
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Down)
        assert view.currentIndex() == model.index_for_id(1)
        QTest.keyClick(view, Qt.Key.Key_Right)
        assert view.isExpanded(model.index_for_id(1))
        QTest.keyClick(view, Qt.Key.Key_Down)
        assert view.currentIndex() == model.index_for_id(2)
        before_activation = bar.playlist_tree.current_playlist_id
        assert selected == [] and before_activation is None
        QTest.keyClick(view, Qt.Key.Key_Return)
        assert selected == [2]
        assert bar.playlist_tree.current_playlist_id == 2
        assert not popup.isVisible()
        assert button.hasFocus()
        # Cancellation after highlighting another item preserves the committed choice.
        QTest.keyClick(button, Qt.Key.Key_Down)
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_End)
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Escape)
        assert selected == [2] and bar.playlist_tree.current_playlist_id == 2
    finally:
        bar.close()


def test_pointer_click_commits_playlist_and_dismisses() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    selected: list[object] = []
    bar.playlist_tree.selected.connect(selected.append)
    try:
        _show(bar)
        _hover_playlists(bar)
        popup = _popup(bar)
        view = popup.findChild(QTreeView, "playlistTree")
        assert view is not None
        model = view.model()
        assert isinstance(model, PlaylistTreeModel)
        point = view.visualRect(model.index_for_id(3)).center()
        QTest.mouseMove(view.viewport(), point)
        assert selected == []
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert selected == [3] and not popup.isVisible()
    finally:
        bar.close()


def test_pointer_and_keyboard_switch_across_all_five_dropdowns() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        first = _button(bar, _DROPDOWNS[0])
        QTest.keyClick(first, Qt.Key.Key_Down)
        for name in _DROPDOWNS[1:]:
            active = next(
                _dropdown(bar, n) for n in _DROPDOWNS if _dropdown(bar, n).isVisible()
            )
            # Left/right switches headings; move off New's submenu first.
            if active is _dropdown(bar, "compactPlaylists"):
                QTest.keyClick(active.focusWidget(), Qt.Key.Key_End)
            QTest.keyClick(active.focusWidget(), Qt.Key.Key_Right)
            assert _dropdown(bar, name).isVisible()
        for name in reversed(_DROPDOWNS):
            active = next(
                _dropdown(bar, n) for n in _DROPDOWNS if _dropdown(bar, n).isVisible()
            )
            button = _button(bar, name)
            QTest.mouseMove(
                active, active.mapFromGlobal(button.mapToGlobal(button.rect().center()))
            )
            assert _dropdown(bar, name).isVisible()
            assert sum(_dropdown(bar, n).isVisible() for n in _DROPDOWNS) == 1
            assert all(
                not _button(bar, other).underMouse()
                for other in _DROPDOWNS
                if other != name
            )
    finally:
        bar.close()


def test_tab_focuses_headings_and_exits_open_menu_to_next_control() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        sync = _button(bar, "compactSyncWithHost")
        sync.setFocus()
        QTest.keyClick(sync, Qt.Key.Key_Tab)
        audio = _button(bar, "compactAudio")
        assert audio.hasFocus() and not _dropdown(bar, "compactAudio").isVisible()
        QTest.keyClick(audio, Qt.Key.Key_Return)
        popup = _dropdown(bar, "compactAudio")
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Tab)
        assert not popup.isVisible() and _button(bar, "compactVideo").hasFocus()
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize(
    "dismiss",
    ["leave", "escape", "outside", "hide", "disconnect", "deactivate", "move", "page"],
)
def test_shared_dropdown_dismissal(name: str, dismiss: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        button = _button(bar, name)
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        assert popup.isVisible()
        outside = popup.mapFromGlobal(bar.mapToGlobal(QPoint(1, 1)))
        if dismiss == "leave":
            QTest.mouseMove(popup, outside)
        elif dismiss == "escape":
            QTest.keyClick(popup, Qt.Key.Key_Escape)
        elif dismiss == "outside":
            QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=outside)
        elif dismiss == "hide":
            bar.hide()
        elif dismiss == "disconnect":
            bar.set_active_ipod(None)
        elif dismiss == "move":
            bar.move(bar.pos() + QPoint(10, 10))
        elif dismiss == "page":
            bar.set_current_page(PageId.SYNESTHESIA)
        else:
            APPLICATION.sendEvent(bar, QEvent(QEvent.Type.ApplicationDeactivate))
        QTest.qWait(220)
        assert not popup.isVisible()
        assert button.property("dropdownOpen") is False
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize("popup_window", [False, True])
def test_unrelated_widget_receives_keyboard_input(
    name: str,
    popup_window: bool,
) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    other = QListWidget(bar)
    if popup_window:
        other.setWindowFlags(Qt.WindowType.Popup)
    other.addItems(["First", "Second"])
    other.setCurrentRow(0)
    try:
        _show(bar)
        button = _button(bar, name)
        QTest.keyClick(button, Qt.Key.Key_Down)
        popup = _dropdown(bar, name)
        assert popup.isVisible()

        other.show()
        other.setFocus(Qt.FocusReason.PopupFocusReason)
        QTest.keyClick(other, Qt.Key.Key_Down)

        assert other.currentRow() == 1
        if popup_window:
            assert APPLICATION.activePopupWidget() is other
            assert not popup.isVisible()
            assert button.property("dropdownOpen") is False
    finally:
        other.close()
        bar.close()


def test_playlist_new_submenu_keeps_parent_open_and_escape_returns_to_parent() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    created: list[object] = []
    bar.playlist_tree.createRequested.connect(created.append)
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Down)
        popup = _dropdown(bar, "compactPlaylists")
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Return)
        menu = bar.playlist_tree.creation_menu
        assert menu.isVisible() and popup.isVisible()
        QTest.qWait(220)
        assert popup.isVisible()
        QTest.keyClick(menu, Qt.Key.Key_Escape)
        assert not menu.isVisible() and popup.isVisible()
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Return)
        QTest.keyClick(menu, Qt.Key.Key_Return)
        assert created == [PlaylistKind.PLAYLIST] and not popup.isVisible()
    finally:
        bar.close()


def test_submenu_click_uses_same_explicit_activation_as_keyboard() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Down)
        popup = _dropdown(bar, "compactPlaylists")
        row = popup.findChild(QToolButton, "compactNewPlaylist")
        assert row is not None
        menu = bar.playlist_tree.creation_menu
        QTest.mousePress(row, Qt.MouseButton.LeftButton)
        QTest.qWait(
            row.style().styleHint(QStyle.StyleHint.SH_ToolButton_PopupDelay) + 50
        )
        assert not menu.isVisible()
        QTest.mouseRelease(row, Qt.MouseButton.LeftButton)
        assert menu.isVisible() and popup.isVisible()
        assert menu.activeAction() is menu.actions()[0]
        assert menu.y() == row.mapToGlobal(QPoint()).y()
    finally:
        bar.close()


def test_routes_availability_and_current_page_markers() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    requested: list[str] = []
    bar.pageRequested.connect(requested.append)
    try:
        for name, labels in (
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
            popup = _dropdown(bar, name)
            assert [a.text() for a in popup.actions()] == labels
            for action in popup.actions():
                action.trigger()
                assert requested[-1] == action.data()
        for name, page in (
            ("compactPhotos", PageId.PHOTOS),
            ("compactGames", PageId.GAMES),
            ("compactSettings", PageId.SETTINGS),
        ):
            _button(bar, name).click()
            assert requested[-1] == page.value
        bar.set_current_page(PageId.TRACKS)
        assert [
            a.data() for a in _dropdown(bar, "compactAudio").actions() if a.isChecked()
        ] == [PageId.TRACKS.value]
        device = _dropdown(bar, "compactDeviceSummary")
        assert not device.actions()[1].isEnabled()
        bar.set_eject_available(True)
        assert device.actions()[1].isEnabled()
        bar.set_device_busy(True)
        assert not device.actions()[2].isEnabled()
        bar.set_review_visible(True)
        bar.set_review_available(True)
        assert _dropdown(bar, "compactMaintenance").actions()[-1].isEnabled()
        active = _active_ipod()
        profile = next(
            p
            for p in DEFAULT_DEVICE_REGISTRY.profiles
            if not p.capabilities.video.supported
            and not p.capabilities.artwork.supports_photos
            and not p.capabilities.supports_games
        )
        bar.set_active_ipod(replace(active, profile=profile))
        assert _button(bar, "compactVideo").isHidden()
        assert _button(bar, "compactPhotos").isHidden()
        assert _button(bar, "compactGames").isHidden()
    finally:
        bar.close()


def test_empty_or_locked_playlists_have_correct_keyboard_targets() -> None:
    workspace = LibraryWorkspace()
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Down)
        popup = _dropdown(bar, "compactPlaylists")
        assert popup.focusWidget() is popup
        QTest.keyClick(popup, Qt.Key.Key_Down)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        assert popup.isVisible()
        popup.hide()
        workspace.load(_workspace().snapshot)
        workspace.set_locked(True)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Down)
        assert isinstance(popup.focusWidget(), QTreeView)
        assert not popup.actions()[0].isEnabled()
    finally:
        bar.close()


@pytest.mark.parametrize("name", _DROPDOWNS)
def test_keyboard_menu_keeps_focus_with_pointer_elsewhere(name: str) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        QTest.keyClick(_button(bar, name), Qt.Key.Key_Up)
        popup = _dropdown(bar, name)
        last = popup.focusWidget()
        QTest.qWait(220)
        assert popup.isVisible() and popup.focusWidget() is last
        QTest.keyClick(last, Qt.Key.Key_Home)
        assert isinstance(popup.focusWidget(), QToolButton)
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_End)
        assert popup.focusWidget() is last
    finally:
        bar.close()


def test_cancelled_heading_press_does_not_leave_pressed_state() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        button = _button(bar, "compactAudio")
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, "compactAudio")
        point = popup.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        QTest.mousePress(popup, Qt.MouseButton.LeftButton, pos=point)
        assert button.isDown()
        QTest.mouseRelease(popup, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
        assert not button.isDown()
    finally:
        bar.close()


def test_nested_menu_outside_click_closes_the_whole_dropdown() -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Return)
        popup = _dropdown(bar, "compactPlaylists")
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_Return)
        menu = bar.playlist_tree.creation_menu
        assert menu.isVisible()
        outside = menu.mapFromGlobal(bar.mapToGlobal(QPoint(1, 1)))
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=outside)
        assert not menu.isVisible() and not popup.isVisible()
    finally:
        bar.close()


@pytest.mark.parametrize("change", ["disable", "hide"])
def test_active_action_becoming_unavailable_moves_keyboard_highlight(
    change: str,
) -> None:
    bar = CompactTopBar(playlists=_workspace())
    bar.set_active_ipod(_active_ipod())
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactAudio"), Qt.Key.Key_Return)
        popup = _dropdown(bar, "compactAudio")
        old = popup.actions()[0]
        if change == "disable":
            old.setEnabled(False)
        else:
            old.setVisible(False)
        focused = popup.focusWidget()
        assert isinstance(focused, QToolButton)
        assert focused.defaultAction() is popup.actions()[1]
    finally:
        bar.close()


def test_long_playlist_menu_scrolls_to_keyboard_highlight_without_selection() -> None:
    workspace = _workspace()
    workspace.load(
        LibrarySnapshot(playlists=tuple(Playlist(i, f"Mix {i:03}") for i in range(100)))
    )
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    selected: list[object] = []
    bar.playlist_tree.selected.connect(selected.append)
    try:
        _show(bar)
        QTest.keyClick(_button(bar, "compactPlaylists"), Qt.Key.Key_Return)
        popup = _dropdown(bar, "compactPlaylists")
        QTest.keyClick(popup.focusWidget(), Qt.Key.Key_End)
        APPLICATION.processEvents()
        view = popup.findChild(QTreeView, "playlistTree")
        scroll = popup.findChild(QScrollArea, "compactPlaylistScroll")
        assert view is not None and scroll is not None
        point = view.viewport().mapTo(
            scroll.viewport(), view.visualRect(view.currentIndex()).center()
        )
        assert scroll.viewport().rect().contains(point)
        assert popup.height() <= 420 and selected == []
        QTest.keyClick(view, Qt.Key.Key_Return)
        assert selected == [99]
    finally:
        bar.close()


def test_normal_hover_does_not_interrupt_playlist_drag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    bar = CompactTopBar(playlists=workspace)
    bar.set_active_ipod(_active_ipod())
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    try:
        _show(bar)
        button = _button(bar, "compactPlaylists")
        data = TrackSelectionMimeData(workspace, (10,))
        APPLICATION.sendEvent(button, _enter(button.rect().center(), data))
        QTest.qWait(550)
        popup = _dropdown(bar, "compactPlaylists")
        assert popup.isVisible() and popup.windowType() == Qt.WindowType.Tool
        for name in _DROPDOWNS:
            target = _button(bar, name)
            QTest.mouseMove(target, target.rect().center())
            assert popup.isVisible()
            assert all(
                not _dropdown(bar, other).isVisible()
                for other in _DROPDOWNS
                if other != "compactPlaylists"
            )
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
    bar.set_active_ipod(_active_ipod())
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
    bar.set_active_ipod(_active_ipod())
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
    bar.set_active_ipod(_active_ipod())
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
    bar.set_active_ipod(_active_ipod())
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
    bar.set_active_ipod(_active_ipod())
    try:
        bar.show()
        _hover_playlists(bar)
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


@pytest.mark.parametrize("name", _DROPDOWNS)
@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
def test_dropdown_heading_restores_idle_appearance_after_leaving(
    name: str,
    mode: AppearanceMode,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    theme.set_mode(mode)
    bar = CompactTopBar(playlists=_workspace(), theme=theme)
    bar.set_active_ipod(_active_ipod())
    try:
        bar.resize(1200, bar.sizeHint().height())
        bar.show()
        bar.activateWindow()
        APPLICATION.processEvents()
        QTest.mouseMove(bar, QPoint(1, 1))
        QTest.qWait(220)
        button = _button(bar, name)
        idle = button.grab().toImage()
        QTest.mouseMove(button, button.rect().center())
        popup = _dropdown(bar, name)
        assert popup.isVisible()
        QTest.mouseMove(popup, popup.mapFromGlobal(bar.mapToGlobal(QPoint(1, 1))))
        QTest.qWait(220)
        assert not popup.isVisible()
        assert not button.underMouse()
        assert button.grab().toImage() == idle
    finally:
        bar.close()
        theme.close()
