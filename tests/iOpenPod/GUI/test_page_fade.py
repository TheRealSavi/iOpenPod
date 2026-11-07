"""Page fades blend rendered frames without postponing or blocking navigation."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.page_fade import PageFade


class _ColorPage(QWidget):
    color = QColor("red")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)
        painter.end()


def _color(page: _ColorPage, color: str) -> None:
    # Change content, not the palette: theme changes deliberately cancel fades.
    page.color = QColor(color)
    page.update()


@pytest.fixture
def page() -> Iterator[_ColorPage]:
    page = _ColorPage()
    page.resize(300, 200)
    _color(page, "red")
    page.show()
    APPLICATION.processEvents()
    yield page
    page.close()


def _animation(fade: PageFade) -> QVariantAnimation:
    animation = fade.findChild(QVariantAnimation)
    assert animation is not None
    if animation.state() == QAbstractAnimation.State.Running:
        animation.pause()
    return animation


def test_fade_blends_then_releases_frame_and_allows_input(page: _ColorPage) -> None:
    fade = PageFade(page)
    fade.transition(lambda: _color(page, "blue"))
    animation = _animation(fade)
    assert page.color == QColor("blue")
    assert page.childAt(20, 20) is None
    assert fade.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert page.grab().toImage().pixelColor(20, 20) == QColor("red")
    animation.setCurrentTime(animation.duration() // 2)
    color = page.grab().toImage().pixelColor(20, 20)
    assert 125 <= color.red() <= 130 and 125 <= color.blue() <= 130
    animation.setCurrentTime(animation.duration())
    assert not fade.isVisible()
    assert page.grab().toImage().pixelColor(20, 20) == QColor("blue")


def test_quick_reversal_starts_from_current_blend(page: _ColorPage) -> None:
    fade = PageFade(page)
    fade.transition(lambda: _color(page, "blue"))
    animation = _animation(fade)
    animation.setCurrentTime(animation.duration() // 2)
    before = page.grab().toImage().pixelColor(20, 20)
    fade.transition(lambda: _color(page, "red"))
    assert page.grab().toImage().pixelColor(20, 20) == before
    animation.setCurrentTime(animation.duration())
    assert page.grab().toImage().pixelColor(20, 20) == QColor("red")


@pytest.mark.parametrize("interrupt", ("hide", "resize", "theme"))
def test_interruption_reveals_current_page(page: _ColorPage, interrupt: str) -> None:
    fade = PageFade(page)
    fade.transition(lambda: _color(page, "blue"))
    assert fade.isVisible()
    if interrupt == "hide":
        page.hide()
        page.show()
    elif interrupt == "resize":
        page.resize(350, 250)
    else:
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.StyleChange))
    assert not fade.isVisible()
    assert _animation(fade).state() == QAbstractAnimation.State.Stopped
    assert page.grab().toImage().pixelColor(20, 20) == QColor("blue")


def test_hidden_navigation_does_not_start_a_fade(page: _ColorPage) -> None:
    fade = PageFade(page)
    page.hide()
    fade.transition(lambda: _color(page, "blue"))
    page.show()
    assert not fade.isVisible()
    assert page.color == QColor("blue")


class _NoAnimationStyle(QProxyStyle):
    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,  # noqa: N803 - Qt keyword name
    ) -> int:
        if hint == QStyle.StyleHint.SH_Widget_Animate:
            return 0
        return super().styleHint(hint, option, widget, returnData)


def test_disabled_host_animation_changes_page_immediately(page: _ColorPage) -> None:
    fade = PageFade(page)
    style = _NoAnimationStyle("Fusion")
    style.setParent(fade)
    fade.setStyle(style)
    fade.transition(lambda: _color(page, "blue"))
    assert not fade.isVisible()
    assert _animation(fade).state() == QAbstractAnimation.State.Stopped
    assert page.grab().toImage().pixelColor(20, 20) == QColor("blue")
