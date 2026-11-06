"""Flow, interrupted crossfades and the visible-only animation lifecycle."""

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.GUI.presentation.now_playing_background import (
    ArtworkBackgroundAnimation,
    now_playing_background,
)
from iOpenPod.GUI.presentation.theme.tokens import DARK_TOKENS, LIGHT_TOKENS, tokens_for
from iOpenPod.GUI.widgets.now_playing_backdrop import NowPlayingBackdrop


def _solid(color: str) -> QImage:
    image = QImage(96, 96, QImage.Format.Format_RGB888)
    image.fill(QColor(color))
    return image


def _cover() -> QImage:
    image = _solid("#af304c")
    painter = QPainter(image)
    painter.fillRect(0, 0, 48, 48, QColor("#f3c25c"))
    painter.fillRect(48, 0, 48, 48, QColor("#112934"))
    painter.fillRect(48, 48, 48, 48, QColor("#4c6fab"))
    painter.end()
    return image


def test_background_substantially_boosts_the_artwork_color() -> None:
    source = _solid("#987c84")
    background = now_playing_background(source, DARK_TOKENS)
    assert background.pixelColor(48, 48).hsvSaturationF() > (
        1.5 * source.pixelColor(48, 48).hsvSaturationF()
    )


def test_fade_blends_then_retargets_from_the_displayed_frame() -> None:
    canvas = QColor(DARK_TOKENS.window)
    animation = ArtworkBackgroundAnimation(canvas)
    animation.set_image(_solid("red"), canvas, animate=False)
    red = animation.image.copy()
    animation.set_image(_solid("blue"), canvas, animate=True)
    assert animation.image == red
    animation.advance(0.6)
    middle = animation.image.copy()
    pixel = middle.pixelColor(48, 48)
    assert 126 <= pixel.red() <= 128 and 126 <= pixel.blue() <= 128
    animation.set_image(_solid("lime"), canvas, animate=True)
    assert animation.image == middle
    animation.advance(0.6)
    pixel = animation.image.pixelColor(48, 48)
    assert 62 <= pixel.red() <= 64 and 126 <= pixel.green() <= 128
    animation.advance(0.6)
    assert animation.image.pixelColor(48, 48) == QColor("lime")
    animation.set_image(QImage(), canvas, animate=True)
    assert animation.image.pixelColor(48, 48) == QColor("lime")
    animation.advance(1.2)
    assert animation.image.pixelColor(48, 48) == canvas
    assert not animation.active


def test_flow_deforms_spatial_colors_continuously_without_exposing_edges() -> None:
    canvas = QColor(DARK_TOKENS.window)
    animation = ArtworkBackgroundAnimation(canvas)
    source = now_playing_background(_cover(), DARK_TOKENS)
    animation.set_image(source, canvas, animate=False)
    first = animation.image.copy()
    animation.advance(5)
    later = animation.image.copy()
    assert first != later
    # Motion is gradual at frame cadence and visible over seconds.
    animation.advance(1 / 30)
    changes: list[int] = []
    for x in range(0, 96, 8):
        for y in range(0, 96, 8):
            before, after = later.pixelColor(x, y), animation.image.pixelColor(x, y)
            assert abs(before.red() - after.red()) <= 2
            assert abs(before.blue() - after.blue()) <= 2
            changes.append(abs(first.pixelColor(x, y).red() - before.red()))
    assert max(changes) >= 5
    for seconds in (0, 3, 11, 47, 180, 3600):
        animation.advance(seconds)
        assert animation.image.size() == source.size()
        for x, y in ((0, 0), (95, 0), (0, 95), (95, 95)):
            pixel = animation.image.pixelColor(x, y)
            assert pixel.alpha() == 255 and pixel != QColor("black")


def _luminance(color: QColor) -> float:
    linear = tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in (color.redF(), color.greenF(), color.blueF())
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


@pytest.mark.parametrize("theme", (*LightTheme, *DarkTheme))
def test_flow_and_crossfade_keep_theme_text_readable(
    theme: LightTheme | DarkTheme,
) -> None:
    tokens = tokens_for(theme)
    canvas = QColor(tokens.window)
    animation = ArtworkBackgroundAnimation(canvas)
    animation.set_image(now_playing_background(_cover(), tokens), canvas, animate=False)
    animation.advance(8)
    animation.set_image(
        now_playing_background(_solid("yellow"), tokens), canvas, animate=True
    )
    for seconds in (0, 0.2, 0.4, 0.6, 13):
        animation.advance(seconds)
        for x in range(0, 96, 8):
            for y in range(0, 96, 8):
                background = _luminance(animation.image.pixelColor(x, y))
                for ink in (tokens.text, tokens.text_secondary):
                    text = _luminance(QColor(ink))
                    ratio = (max(background, text) + 0.05) / (
                        min(background, text) + 0.05
                    )
                    assert ratio >= 4.5


def test_widget_stops_hidden_and_minimized_and_resumes_without_jumping() -> None:
    window = QWidget()
    backdrop = NowPlayingBackdrop(DARK_TOKENS, window)
    backdrop.setGeometry(0, 0, 300, 200)
    backdrop.set_artwork(_cover(), DARK_TOKENS)
    timer = backdrop.findChild(QTimer)
    assert timer is not None and not timer.isActive()
    try:
        window.show()
        APPLICATION.processEvents()
        assert timer.isActive()
        initial = backdrop.grab().toImage()
        QTest.qWait(80)
        assert backdrop.grab().toImage() != initial
        window.hide()
        hidden = backdrop.grab().toImage()
        assert not timer.isActive()
        QTest.qWait(80)
        assert backdrop.grab().toImage() == hidden
        window.show()
        assert timer.isActive()
        assert backdrop.grab().toImage() == hidden
        QTest.qWait(80)
        assert backdrop.grab().toImage() != hidden
        window.showMinimized()
        APPLICATION.processEvents()
        assert not timer.isActive()
        window.showNormal()
        APPLICATION.processEvents()
        assert timer.isActive()
    finally:
        window.close()


def test_disabled_animation_theme_changes_and_invalidation_are_immediate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = QWidget()
    backdrop = NowPlayingBackdrop(DARK_TOKENS, window)
    backdrop.setGeometry(0, 0, 300, 200)
    timer = backdrop.findChild(QTimer)
    assert timer is not None

    def animations_disabled(_backdrop: NowPlayingBackdrop) -> bool:
        return False

    try:
        window.show()
        APPLICATION.processEvents()
        backdrop.set_artwork(_solid("red"), DARK_TOKENS)
        assert timer.isActive()
        monkeypatch.setattr(
            NowPlayingBackdrop, "_animations_enabled", animations_disabled
        )
        APPLICATION.sendEvent(backdrop, QEvent(QEvent.Type.StyleChange))
        assert not timer.isActive()
        assert backdrop.grab().toImage().pixelColor(0, 0) == now_playing_background(
            _solid("red"), DARK_TOKENS
        ).pixelColor(0, 0)
        backdrop.set_artwork(_solid("blue"), DARK_TOKENS)
        assert not timer.isActive()
        assert backdrop.grab().toImage().pixelColor(0, 0) == now_playing_background(
            _solid("blue"), DARK_TOKENS
        ).pixelColor(0, 0)
        monkeypatch.undo()
        backdrop.set_artwork(_solid("blue"), LIGHT_TOKENS)
        light_blue = backdrop.grab().toImage()
        assert light_blue.pixelColor(0, 0) == now_playing_background(
            _solid("blue"), LIGHT_TOKENS
        ).pixelColor(0, 0)
        backdrop.set_artwork(QImage(), LIGHT_TOKENS)
        assert timer.isActive()
        assert backdrop.grab().toImage() == light_blue
        # Session invalidation must discard even an already-running fade to empty.
        backdrop.set_artwork(QImage(), LIGHT_TOKENS, animate=False)
        assert backdrop.grab().toImage().pixelColor(0, 0) == QColor(LIGHT_TOKENS.window)
        assert not timer.isActive()
    finally:
        window.close()
