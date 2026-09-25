"""Tests for palette-aware glyph rendering."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from iOpenPod.GUI.presentation.icons import glyph_icon


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


@pytest.mark.parametrize("name", ("music", "play-next", "play-last", "bell"))
def test_glyph_icon_renders_visible_pixels(name: str) -> None:
    icon = glyph_icon(name, 18, QColor("#176FD1"), 2.0)
    image = icon.pixmap(QSize(18, 18)).toImage()

    assert not icon.isNull()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )
