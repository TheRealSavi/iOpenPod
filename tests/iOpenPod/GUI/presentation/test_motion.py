"""Motion responds promptly, retains velocity, and respects the Host preference."""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, QRect, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.motion_test_support import disable_motion

from iOpenPod.GUI.presentation.motion import (
    MOTION,
    SpringAnimation,
    SpringPropertyAnimation,
    animations_enabled,
    fade_curve,
)
from iOpenPod.GUI.widgets.icon_segmented_control import IconSegmentedControl
from iOpenPod.GUI.widgets.settings_scope import SettingsScopeSwitcher
from iOpenPod.GUI.widgets.settings_tab import SettingsExampleImage
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iOpenPod.GUI.widgets.toggle_switch import ToggleSwitch


def test_spring_responds_early_and_settles_monotonically_without_bounce() -> None:
    owner = QWidget()
    animation = SpringAnimation(owner)
    animation.retarget(0.0, 100.0, MOTION.panel_enter_ms)
    animation.pause()
    values: list[float] = []
    for time in range(0, animation.duration() + 1, 16):
        animation.setCurrentTime(time)
        values.append(float(animation.currentValue()))
    assert values[0] == 0.0 and values[-1] == 100.0
    assert values == sorted(values)
    assert 25 < values[3] < 65  # Visible response by 48 ms.
    assert 90 < values[10] < 100  # Mostly arrived, still settling at 160 ms.
    assert animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("paused", [False, True])
def test_reversal_preserves_position_and_velocity(paused: bool) -> None:
    owner = QWidget()
    animation = SpringAnimation(owner)
    animation.retarget(0.0, 100.0, MOTION.panel_enter_ms)
    if paused:
        animation.pause()
    animation.setCurrentTime(31)
    previous = float(animation.currentValue())
    animation.setCurrentTime(32)
    position = float(animation.currentValue())
    incoming_speed = position - previous
    emitted: list[object] = []
    animation.valueChanged.connect(emitted.append)
    animation.retarget(position, -100.0, MOTION.panel_exit_ms)
    assert animation.currentValue() == position
    assert all(value == position for value in emitted)
    animation.pause()
    animation.setCurrentTime(1)
    outgoing_speed = float(animation.currentValue()) - position
    # It initially continues moving, rather than abruptly reversing or stopping.
    assert outgoing_speed == pytest.approx(incoming_speed, rel=0.18)
    animation.setCurrentTime(40)
    assert float(animation.currentValue()) < position
    animation.setCurrentTime(animation.duration())
    assert animation.currentValue() == -100.0


def test_cancel_discards_velocity_and_frame_skips_do_not_change_the_path() -> None:
    owner = QWidget()
    first, second = SpringAnimation(owner), SpringAnimation(owner)
    for animation in (first, second):
        animation.retarget(0.0, 100.0, MOTION.panel_enter_ms)
        animation.pause()
    for time in range(1, 81):
        first.setCurrentTime(time)
    second.setCurrentTime(80)
    assert first.currentValue() == second.currentValue()
    position = float(first.currentValue())
    first.stop()
    first.retarget(position, 0.0, MOTION.panel_exit_ms)
    first.setCurrentTime(1)
    assert 0 < position - float(first.currentValue()) < 0.1


@pytest.mark.parametrize(
    "start,target",
    [
        (0, 64),
        (QPoint(0, -360), QPoint(0, 0)),
        (QRect(0, 0, 32, 32), QRect(32, 0, 32, 32)),
        (QRectF(2.5, 0, 32, 32), QRectF(35.5, 0, 64, 32)),
    ],
)
def test_native_value_types_finish_exactly(start: object, target: object) -> None:
    assert isinstance(start, (int, QPoint, QRect, QRectF))
    assert isinstance(target, (int, QPoint, QRect, QRectF))
    owner = QWidget()
    animation = SpringAnimation(owner)
    animation.retarget(start, target, MOTION.control_ms)
    animation.pause()
    animation.setCurrentTime(60)
    assert type(animation.currentValue()) is type(start)
    assert animation.currentValue() != start and animation.currentValue() != target
    animation.setCurrentTime(animation.duration())
    assert animation.currentValue() == target


def test_property_binding_retargets_without_emitting_a_stale_position() -> None:
    widget = QWidget()
    widget.move(0, 0)
    animation = SpringPropertyAnimation(widget, b"pos", widget)
    animation.retarget(widget.pos(), QPoint(320, 0), MOTION.panel_enter_ms)
    animation.pause()
    animation.setCurrentTime(80)
    position = widget.pos()
    assert 0 < position.x() < 320
    animation.retarget(position, QPoint(0, 0), MOTION.panel_exit_ms)
    assert widget.pos() == position
    animation.setCurrentTime(animation.duration())
    assert widget.pos() == QPoint(0, 0)


def test_fade_curve_is_bounded_and_reveals_most_content_by_half_time() -> None:
    curve = fade_curve()
    values = [curve.valueForProgress(step / 100) for step in range(101)]
    assert values[0] == 0.0 and values[-1] == 1.0
    assert values == sorted(values)
    assert 0.75 < values[50] < 0.98


def test_zero_animation_duration_disables_motion_in_current_qt_styles() -> None:
    widget = QWidget()
    widget.setStyleSheet("widget-animation-duration: 0")
    assert not animations_enabled(widget)


@pytest.mark.parametrize("disabled", [False, True])
def test_selectors_and_switches_settle_on_hide_or_without_host_motion(
    disabled: bool,
) -> None:
    scope = SettingsScopeSwitcher()
    buttons = (IconButton("grid", "Grid"), IconButton("list", "List"))
    segments = IconSegmentedControl(buttons)
    toggle = ToggleSwitch()
    widgets = (scope, segments, toggle)
    try:
        for widget in widgets:
            if disabled:
                disable_motion(widget)
            widget.show()
        APPLICATION.processEvents()
        scope.select_device(True)
        buttons[1].click()
        toggle.click()
        assert scope.device_selected and buttons[1].isChecked() and toggle.isChecked()
        for widget in widgets:
            animation = widget.findChild(QVariantAnimation)
            assert animation is not None
            if disabled:
                assert animation.state() == QAbstractAnimation.State.Stopped
            else:
                assert animation.state() == QAbstractAnimation.State.Running
                widget.hide()
                assert animation.state() == QAbstractAnimation.State.Stopped
    finally:
        for widget in widgets:
            widget.close()


@pytest.mark.parametrize("hidden", [False, True])
def test_settings_artwork_changes_immediately_without_motion(hidden: bool) -> None:
    owner = QWidget()
    image = SettingsExampleImage(owner)
    image.resize(200, 200)
    if not hidden:
        disable_motion(image)
        owner.show()
        APPLICATION.processEvents()
    red, blue = QPixmap(200, 200), QPixmap(200, 200)
    red.fill(QColor("red"))
    blue.fill(QColor("blue"))
    try:
        image.set_image(red, animate=False)
        image.set_image(blue, animate=True)
        assert image.frame().pixelColor(100, 100) == QColor("blue")
        animation = image.findChild(QVariantAnimation)
        assert animation is not None
        assert animation.state() == QAbstractAnimation.State.Stopped
    finally:
        owner.close()
