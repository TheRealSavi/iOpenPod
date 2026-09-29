"""All active statuses remain inspectable while the shared status text rotates."""

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QMainWindow
from pytest import mark
from tests.iOpenPod.app.core.test_status import (
    _wait_until,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.status import ApplicationStatus, StatusAction, StatusProgress
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.status_controls import StatusBarControls, StatusControls
from iOpenPod.GUI.widgets.status_list import StatusListButton


def _finish_popup_animation(popup: QFrame) -> None:
    animation = popup.findChild(QPropertyAnimation, "activeStatusesAnimation")
    assert animation is not None
    animation.setCurrentTime(animation.duration())
    APPLICATION.processEvents()


def test_status_popup_slides_up_and_down_with_distinct_curves() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        button = window.findChild(StatusListButton)
        popup = window.findChild(QFrame, "activeStatusesPopup")
        assert button is not None and popup is not None
        surface = popup.findChild(QFrame, "activeStatusesSurface")
        assert surface is not None
        animation = popup.findChild(QPropertyAnimation, "activeStatusesAnimation")
        assert animation is not None

        button.click()
        APPLICATION.processEvents()
        start = animation.startValue()
        rest = animation.endValue()
        assert start.y() - rest.y() >= popup.height() - LAYOUT.space_md
        host_pos = popup.pos()
        assert (
            popup.geometry().bottom() < button.mapToGlobal(button.rect().topLeft()).y()
        )
        initial_image = popup.grab().toImage()
        assert (
            initial_image.pixelColor(popup.width() // 2, popup.height() // 2).alpha()
            == 0
        )
        assert animation.easingCurve().type() == QEasingCurve.Type.OutBack
        animation.setCurrentTime(animation.duration() // 3)
        assert popup.pos() == host_pos
        assert rest.y() < surface.y() < start.y()
        assert surface.geometry().bottom() > popup.rect().bottom()
        partial_image = popup.grab().toImage()
        assert partial_image.pixelColor(popup.width() // 2, 4).alpha() == 0
        assert (
            partial_image.pixelColor(popup.width() // 2, popup.height() - 4).alpha()
            == 255
        )
        _finish_popup_animation(popup)
        assert popup.pos() == host_pos

        popup.close()
        APPLICATION.processEvents()
        assert popup.isVisible()
        assert animation.startValue() == rest
        assert animation.endValue() == start
        assert animation.easingCurve().type() == QEasingCurve.Type.InCubic
        animation.setCurrentTime(animation.duration() // 2)
        assert popup.pos() == host_pos
        _finish_popup_animation(popup)
        assert not popup.isVisible()

        button.click()
        animation.setCurrentTime(animation.duration() // 3)
        interrupted_at = surface.pos()
        button.click()
        assert animation.startValue() == interrupted_at
        _finish_popup_animation(popup)
        assert not popup.isVisible()

        button.click()
        _finish_popup_animation(popup)
        button.click()
        animation.setCurrentTime(animation.duration() // 2)
        exiting_at = surface.pos()
        button.click()
        assert animation.startValue() == exiting_at
        assert animation.endValue() == rest
        _finish_popup_animation(popup)
        assert popup.isVisible()
    finally:
        window.close()
        context.shutdown()


@mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
def test_status_popup_has_rounded_opaque_theme_surface(mode: AppearanceMode) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        context.theme_manager.set_mode(mode)
        window.show()
        APPLICATION.processEvents()
        button = window.findChild(StatusListButton)
        popup = window.findChild(QFrame, "activeStatusesPopup")
        assert button is not None and popup is not None
        button.click()
        APPLICATION.processEvents()
        _finish_popup_animation(popup)

        image = popup.grab().toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(40, 100) == QColor(context.theme_manager.tokens.surface)
    finally:
        window.close()
        context.shutdown()


def test_bell_press_closes_popup_on_release_and_later_click_reopens_it() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        button = window.findChild(StatusListButton)
        popup = window.findChild(QFrame, "activeStatusesPopup")
        assert button is not None and popup is not None
        button.click()
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        assert popup.isVisible()

        # Hold the popup's mouse grab through a press on the bell, then close
        # on release so the same click cannot also reopen it.
        outside = popup.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        QTest.mousePress(popup, Qt.MouseButton.LeftButton, pos=outside)
        APPLICATION.processEvents()
        assert popup.isVisible()
        QTest.mouseRelease(popup, Qt.MouseButton.LeftButton, pos=outside)
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        assert not popup.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        assert popup.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        assert not popup.isVisible()

        button.click()
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        QTest.mousePress(popup, Qt.MouseButton.LeftButton, pos=QPoint(-1, -1))
        APPLICATION.processEvents()
        _finish_popup_animation(popup)
        assert not popup.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_corner_button_opens_live_list_and_closing_does_not_clear_statuses() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        context.status.show("backup", "Capturing 1 of 2 files…")
        context.status.show("analysis", "Analyzing Track…")
        window.show()
        APPLICATION.processEvents()
        button = window.findChild(StatusListButton)
        assert button is not None and button.isVisible()
        assert button.text() == "2"
        assert button.width() < 60
        assert button.height() < 36
        button.click()
        APPLICATION.processEvents()
        popup = window.findChild(QFrame, "activeStatusesPopup")
        statuses = window.findChild(QListWidget, "activeStatusesList")
        empty = window.findChild(QLabel, "activeStatusesEmpty")
        assert popup is not None and statuses is not None and empty is not None
        _finish_popup_animation(popup)
        assert popup.isVisible()
        assert [statuses.item(row).text() for row in range(statuses.count())] == [
            "Capturing 1 of 2 files…",
            "Analyzing Track…",
        ]
        assert (
            popup.geometry().bottom() < button.mapToGlobal(button.rect().topLeft()).y()
        )

        statuses.setCurrentRow(1)
        selected = statuses.currentItem()
        context.status.show("backup", "Capturing 2 of 2 files…")
        assert statuses.item(0).text() == "Capturing 2 of 2 files…"
        assert statuses.currentItem() is selected
        # Check selection preservation across one deterministic rotation.
        context.status._rotate()  # pyright: ignore[reportPrivateUsage]
        assert window.statusBar().currentMessage() == "Capturing 2 of 2 files…"
        assert statuses.currentItem() is selected

        QTest.keyClick(statuses, Qt.Key.Key_Escape)
        _finish_popup_animation(popup)
        assert not popup.isVisible()
        assert len(context.status.active_messages) == 2
        button.click()
        context.status.clear("backup")
        assert statuses.count() == 1 and statuses.currentItem() is selected
        context.status.show("notice", "Temporary notice", timeout_ms=10)
        assert button.text() == "2"
        _wait_until(lambda: statuses.count() == 1)
        assert statuses.count() == 1 and button.text() == "1"
        context.status.clear("analysis")
        assert statuses.count() == 0
        assert empty.isVisible()
        assert not button.text()
        assert "No Active iPod" in window.statusBar().currentMessage()
    finally:
        window.close()
        context.shutdown()


def test_popup_shows_progress_and_can_request_a_status_action() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    requests: list[tuple[str, str]] = []

    def record_action(source: str, key: str) -> None:
        requests.append((source, key))

    context.status.actionRequested.connect(record_action)
    try:
        context.status.show(
            "backup",
            "Capturing a fairly long filename from the iPod for this Backup Snapshot…",
            progress=StatusProgress(75, 100, "song.m4a"),
        )
        context.status.show(
            "chaptered",
            "Encoding…",
            progress=StatusProgress(),
            action=StatusAction("cancel", "Cancel"),
        )
        window.show()
        APPLICATION.processEvents()
        button = window.findChild(StatusListButton)
        popup = window.findChild(QFrame, "activeStatusesPopup")
        assert button is not None and popup is not None
        button.click()
        APPLICATION.processEvents()
        _finish_popup_animation(popup)

        controls = {
            control.property("statusSource"): control
            for control in popup.findChildren(StatusControls)
        }
        assert set(controls) == {"backup", "chaptered"}
        assert controls["backup"].progress.value() == 7_500
        assert controls["backup"].progress.toolTip() == "song.m4a"
        assert controls["backup"].action.isHidden()
        assert controls["chaptered"].progress.minimum() == 0
        assert controls["chaptered"].progress.maximum() == 0
        assert controls["chaptered"].action.text() == "Cancel"
        assert (
            controls["chaptered"].action.height()
            >= controls["chaptered"].action.sizeHint().height()
        )
        backup_row = controls["backup"].parentWidget()
        assert backup_row is not None
        backup_label = backup_row.findChild(QLabel)
        assert backup_label is not None
        assert backup_label.height() >= 2 * backup_label.fontMetrics().height()

        bar_controls = window.findChild(StatusBarControls)
        assert bar_controls is not None
        assert bar_controls.property("statusSource") == "chaptered"
        context.status._rotate()  # pyright: ignore[reportPrivateUsage]
        assert bar_controls.property("statusSource") == "backup"
        assert bar_controls.progress.value() == 7_500
        assert bar_controls.action.isHidden()

        controls["chaptered"].action.click()
        assert requests == [("chaptered", "cancel")]
        context.status.clear("chaptered")
        APPLICATION.processEvents()
        assert len(popup.findChildren(StatusControls)) >= 1
        assert controls["backup"].progress.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_status_popup_scrolls_long_messages_and_stays_within_the_screen() -> None:
    window = QMainWindow()
    status = ApplicationStatus(window)
    button = StatusListButton(status, window)
    window.statusBar().addPermanentWidget(button)
    for index in range(25):
        status.show(str(index), f"Status {index}: " + "Long progress details " * 12)
    try:
        window.resize(960, 620)
        window.show()
        APPLICATION.processEvents()
        QTest.keyClick(button, Qt.Key.Key_Space)
        APPLICATION.processEvents()
        popup = window.findChild(QFrame, "activeStatusesPopup")
        statuses = window.findChild(QListWidget, "activeStatusesList")
        assert popup is not None and statuses is not None and popup.isVisible()
        _finish_popup_animation(popup)
        assert button.screen().availableGeometry().contains(popup.geometry())
        assert statuses.count() == 25
        assert statuses.verticalScrollBar().maximum() > 0
        assert (
            statuses.visualItemRect(statuses.item(0)).height()
            > statuses.fontMetrics().height() * 2
        )
        statuses.setCurrentRow(24)
        statuses.scrollToItem(statuses.item(24))
        APPLICATION.processEvents()
        assert (
            statuses.viewport()
            .rect()
            .intersects(statuses.visualItemRect(statuses.item(24)))
        )
        QTest.keyClick(statuses, Qt.Key.Key_Escape)
        _finish_popup_animation(popup)
        assert not popup.isVisible()
    finally:
        window.close()
        window.deleteLater()
