"""Device-card navigation leaves embedded device actions independent."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.widgets.sidebar import DeviceCard, Sidebar
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint


def _active_ipod() -> ActiveIPod:
    profile = next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("summary-test"),
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
        library=LibrarySnapshot(device_name="My iPod"),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=1024, modified_ns=0, device=0, inode=0, sha256="0" * 64
        ),
    )


@pytest.mark.parametrize(
    "target_name",
    [
        "deviceCard",
        "deviceIcon",
        "deviceModel",
        "deviceSummary",
        "deviceStorage",
        "deviceMetricLabel",
        "deviceMetricValue",
        "deviceDatabase",
        "deviceDatabaseValue",
    ],
)
def test_passive_device_card_content_opens_summary(target_name: str) -> None:
    card = DeviceCard()
    card.set_active_ipod(_active_ipod())
    spy = QSignalSpy(card.summaryRequested)
    try:
        card.show()
        APPLICATION.processEvents()
        target = (
            card
            if target_name == "deviceCard"
            else card.findChild(QWidget, target_name)
        )
        assert target is not None
        position = QPoint(2, 2) if target is card else target.rect().center()
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=position)
        assert spy.count() == 1
        QTest.mouseClick(target, Qt.MouseButton.RightButton, pos=position)
        assert spy.count() == 1
    finally:
        card.close()


def test_embedded_actions_and_rename_editor_do_not_open_summary() -> None:
    active = _active_ipod()
    workspace = LibraryWorkspace()
    workspace.load(active.library)
    card = DeviceCard()
    card.set_workspace(workspace)
    card.set_active_ipod(active)
    card.set_eject_available(True)
    summary = QSignalSpy(card.summaryRequested)
    eject = QSignalSpy(card.ejectRequested)
    choose = QSignalSpy(card.chooseRequested)
    try:
        card.show()
        APPLICATION.processEvents()
        name = card.findChild(QAbstractButton, "deviceName")
        eject_button = card.findChild(QAbstractButton, "ejectActiveIPod")
        assert name is not None and eject_button is not None
        QTest.mouseClick(eject_button, Qt.MouseButton.LeftButton)
        assert eject.count() == 1
        chooser = next(
            button
            for button in card.findChildren(QAbstractButton)
            if button.text() == "Choose iPod…"
        )
        QTest.mouseClick(chooser, Qt.MouseButton.LeftButton)
        assert choose.count() == 1
        QTest.mouseClick(name, Qt.MouseButton.LeftButton)
        editor = card.findChild(QLineEdit, "renameIPod")
        cancel = card.findChild(QAbstractButton, "renameIPodCancel")
        assert editor is not None and editor.isVisible() and cancel is not None
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
        editor.setText("Renamed")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        assert workspace.device_name == "Renamed"
        QTest.mouseClick(name, Qt.MouseButton.LeftButton)
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert not editor.isVisible()
        assert summary.count() == 0
        card.set_busy(True)
        card.set_eject_available(False)
        for disabled in (name, eject_button, chooser):
            assert not disabled.isEnabled()
            QTest.mouseClick(disabled, Qt.MouseButton.LeftButton)
            # A disabled child's event may propagate to the parent in Qt.
            QTest.mouseClick(
                card,
                Qt.MouseButton.LeftButton,
                pos=disabled.mapTo(card, disabled.rect().center()),
            )
        assert summary.count() == 0
    finally:
        card.close()


@pytest.mark.parametrize("mode", (AppearanceMode.LIGHT, AppearanceMode.DARK))
@pytest.mark.parametrize(
    "action",
    (
        "deviceName",
        "ejectActiveIPod",
        "choose",
        "renameIPod",
        "renameIPodApply",
        "renameIPodCancel",
    ),
)
def test_summary_hover_clears_over_embedded_actions(
    action: str, mode: AppearanceMode
) -> None:
    context = build_context()
    context.theme_manager.set_mode(mode)
    active = _active_ipod()
    workspace = LibraryWorkspace()
    workspace.load(active.library)
    card = DeviceCard()
    card.set_workspace(workspace)
    card.set_active_ipod(active)
    card.set_eject_available(True)
    try:
        card.show()
        APPLICATION.processEvents()
        renaming = action.startswith("renameIPod")
        if renaming:
            card.start_rename()
            APPLICATION.processEvents()
        target: QWidget | None
        if action == "choose":
            target = next(
                button
                for button in card.findChildren(QAbstractButton)
                if button.text() == "Choose iPod…"
            )
        else:
            target = card.findChild(QWidget, action)
        assert target is not None and target.isVisible()
        sample = QPoint(3, card.height() // 2) * card.devicePixelRatioF()
        for busy in (False,) if renaming else (False, True):
            card.set_busy(busy)
            card.set_eject_available(not busy)
            QTest.mouseMove(card, QPoint(2, 2))
            APPLICATION.processEvents()
            assert card.grab().toImage().pixelColor(sample) == QColor(
                context.theme_manager.tokens.surface_hover
            )
            QTest.mouseMove(target, target.rect().center())
            APPLICATION.processEvents()
            assert card.grab().toImage().pixelColor(sample) == QColor(
                context.theme_manager.tokens.window
            )
        card.set_summary_selected(True)
        assert card.grab().toImage().pixelColor(sample) == QColor(
            context.theme_manager.tokens.surface_selected
        )
        card.set_summary_selected(False)
        QTest.mouseMove(card, QPoint(2, 2))
        APPLICATION.processEvents()
        assert card.grab().toImage().pixelColor(sample) == QColor(
            context.theme_manager.tokens.surface_hover
        )
        QTest.mouseMove(card, QPoint(-10, -10))
        APPLICATION.processEvents()
        assert card.grab().toImage().pixelColor(sample) == QColor(
            context.theme_manager.tokens.window
        )
    finally:
        card.close()
        context.shutdown()


def test_summary_keyboard_navigation_and_disconnect_invalidate_pending_click() -> None:
    card = DeviceCard()
    spy = QSignalSpy(card.summaryRequested)
    try:
        card.show()
        APPLICATION.processEvents()
        assert card.focusPolicy() == Qt.FocusPolicy.NoFocus
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        assert spy.count() == 0
        card.set_active_ipod(_active_ipod())
        card.setFocus()
        APPLICATION.processEvents()
        assert card.focusPolicy() == Qt.FocusPolicy.StrongFocus
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            QTest.keyClick(card, key)
        assert spy.count() == 3
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(-1, -1))
        assert spy.count() == 3
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        card.set_active_ipod(None)
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        QTest.keyClick(card, Qt.Key.Key_Return)
        assert spy.count() == 3
        assert card.property("summaryAvailable") is False
    finally:
        card.close()


def test_shell_routes_card_to_summary_and_clears_selection_on_library_navigation() -> (
    None
):
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        context.device_controller.activeIPodChanged.emit(_active_ipod())
        APPLICATION.processEvents()
        sidebar = window.findChild(Sidebar)
        card = window.findChild(DeviceCard)
        pages = window.findChild(QStackedWidget, "pageStack")
        page = window.findChild(DeviceSummaryPage)
        assert sidebar is not None and card is not None
        assert pages is not None and page is not None
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        assert pages.currentWidget() is page
        assert card.property("summarySelected") is True
        name = page.findChild(QLabel, "deviceSummaryName")
        assert name is not None and name.text() == "My iPod"
        workspace = context.library_workspace
        workspace.rename_device("Live name", workspace.edit_revision)
        assert name.text() == "Live name"
        sidebar.pageRequested.emit(PageId.ALBUMS.value)
        assert pages.currentWidget() is not page
        assert card.property("summarySelected") is False
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        context.device_controller.activeIPodChanged.emit(None)
        assert card.property("summaryAvailable") is False
        assert pages.currentWidget() is page
        assert name.text() == "No Active iPod"
    finally:
        window.close()
        context.shutdown()
