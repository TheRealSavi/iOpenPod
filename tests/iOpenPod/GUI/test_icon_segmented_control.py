"""Page selectors retain native controls while their highlight slides."""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPropertyAnimation, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.icon_segmented_control import IconSegmentedControl
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iOpenPod.GUI.widgets.track_media_switch import TrackMediaSwitch


@pytest.mark.parametrize("media_scope", [False, True])
def test_page_switchers_slide_reverse_and_keep_icon_only_keyboard_controls(
    media_scope: bool,
) -> None:
    page = TrackMediaSwitch() if media_scope else LibraryToolbar()
    if isinstance(page, LibraryToolbar):
        page.viewModeChanged.connect(page.set_view_mode)
        changes = QSignalSpy(page.viewModeChanged)
        control = page.findChild(IconSegmentedControl)
    else:
        changes = QSignalSpy(page.allMediaChanged)
        control = page
    assert control is not None
    page.show()
    APPLICATION.processEvents()
    buttons = control.findChildren(IconButton)
    selector = control.findChild(QWidget, "iconSegmentSelector")
    animation = control.findChild(QPropertyAnimation)
    assert selector is not None and animation is not None
    first, second = buttons
    try:
        assert control.height() == 36 and control.width() == 68
        assert all(
            button.text() == "" and button.accessibleName() for button in buttons
        )
        assert first.isChecked() and selector.geometry() == first.geometry()
        QTest.mouseClick(second, Qt.MouseButton.LeftButton)
        assert changes.count() == 1
        assert second.isChecked() and not first.isChecked()
        assert animation.state() is QAbstractAnimation.State.Running
        animation.setCurrentTime(animation.duration() // 2)
        assert first.x() < selector.x() < second.x()
        middle = selector.geometry()
        QTest.mouseClick(first, Qt.MouseButton.LeftButton)
        assert animation.startValue() == middle
        animation.setCurrentTime(animation.duration())
        assert selector.geometry() == first.geometry()

        QTest.keyClick(first, Qt.Key.Key_Right)
        assert second.isChecked() and second.hasFocus()
        animation.setCurrentTime(animation.duration())
        assert selector.geometry() == second.geometry()
        QTest.keyClick(second, Qt.Key.Key_Home)
        assert first.isChecked() and first.hasFocus()
        QTest.keyClick(first, Qt.Key.Key_Space)
        assert first.isChecked()

        page.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        APPLICATION.processEvents()
        assert selector.geometry() == first.geometry()
        QTest.keyClick(first, Qt.Key.Key_Left)
        assert second.isChecked()
        animation.setCurrentTime(animation.duration())
        assert selector.geometry() == second.geometry()
    finally:
        page.close()


def test_programmatic_view_change_is_silent_and_restores_highlight_on_show() -> None:
    toolbar = LibraryToolbar()
    control = toolbar.findChild(IconSegmentedControl)
    assert control is not None
    selector = control.findChild(QWidget, "iconSegmentSelector")
    animation = control.findChild(QPropertyAnimation)
    assert selector is not None and animation is not None
    grid, list_view = control.findChildren(IconButton)
    changes = QSignalSpy(toolbar.viewModeChanged)
    toolbar.set_view_mode("list")
    toolbar.show()
    APPLICATION.processEvents()
    try:
        assert changes.count() == 0
        assert list_view.isChecked()
        assert selector.geometry() == list_view.geometry()
        toolbar.set_view_mode("grid")
        assert changes.count() == 0
        assert animation.state() is QAbstractAnimation.State.Running
        toolbar.hide()
        toolbar.set_view_mode("list")
        toolbar.show()
        APPLICATION.processEvents()
        assert selector.geometry() == list_view.geometry()
        assert animation.state() is QAbstractAnimation.State.Stopped
        assert not grid.isChecked()
    finally:
        toolbar.close()
