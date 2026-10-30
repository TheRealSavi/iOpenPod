"""Tests for palette-aware glyph rendering."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from iOpenPod.app.genius_mixes import MIX_CATALOG
from iOpenPod.GUI.presentation.icons import glyph_icon, phase_wordmark


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_phase_wordmark_keeps_wide_shape_and_palette_color(dpr: float) -> None:
    color = QColor("#68B7FF")
    pixmap = phase_wordmark(14, color, dpr)
    assert pixmap.devicePixelRatio() == dpr
    assert pixmap.width() > 4 * pixmap.height()
    image = pixmap.toImage()
    pixels = [
        image.pixelColor(x, y)
        for y in range(image.height())
        for x in range(image.width())
    ]
    assert any(pixel.alpha() > 200 and pixel.name() == color.name() for pixel in pixels)


@pytest.mark.parametrize(
    "name", ("music", "all-media", "play-next", "play-last", "bell", "ipod", "atom")
)
def test_glyph_icon_renders_visible_pixels(name: str) -> None:
    icon = glyph_icon(name, 18, QColor("#176FD1"), 2.0)
    image = icon.pixmap(QSize(18, 18)).toImage()

    assert not icon.isNull()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def test_every_genius_mix_has_a_distinct_visible_glyph() -> None:
    silhouettes: set[tuple[int, ...]] = set()
    for definition in MIX_CATALOG:
        icon = glyph_icon(f"genius-mixes/{definition.key}", 40, QColor("#176FD1"))
        image = icon.pixmap(QSize(40, 40)).toImage()
        silhouette = tuple(
            image.pixelColor(x, y).alpha()
            for y in range(image.height())
            for x in range(image.width())
        )
        assert max(silhouette) > 0, definition.key
        assert silhouette not in silhouettes, definition.key
        silhouettes.add(silhouette)
