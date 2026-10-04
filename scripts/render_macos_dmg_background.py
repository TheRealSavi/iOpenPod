"""Render the editable DMG artwork at Finder's correct physical image size."""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ARTWORK = Path(__file__).resolve().parents[1] / "packaging/macos"


def render_background() -> Path:
    """Export the SVG at 2x, encoding 144 dpi rather than Qt's host default."""
    if not QFontDatabase.families():
        raise RuntimeError("No fonts available; run with Qt's native platform plugin")
    # Keep the wallpaper separate and editable; embed only for rendering so the
    # SVG image reference resolves identically on every host and working directory.
    backdrop = base64.b64encode((ARTWORK / "dmg-backdrop.png").read_bytes()).decode()
    source = (ARTWORK / "dmg-background.svg").read_text(encoding="utf-8")
    source = source.replace("dmg-backdrop.png", f"data:image/png;base64,{backdrop}")
    renderer = QSvgRenderer(QByteArray(source.encode()))
    if not renderer.isValid():
        raise ValueError("Invalid DMG background SVG")
    logical = renderer.viewBoxF().size()
    image = QImage(
        round(logical.width() * 2),
        round(logical.height() * 2),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    # Finder converts image resolution to 72-point coordinates. Qt's default
    # 96 dpi makes a 2x image 1.5 times too large, displacing the arrow and copy.
    pixels_per_meter = round(144 / 0.0254)
    image.setDotsPerMeterX(pixels_per_meter)
    image.setDotsPerMeterY(pixels_per_meter)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    output = ARTWORK / "dmg-background.png"
    if not image.save(str(output)):
        raise OSError(f"Could not save {output}")
    return output


if __name__ == "__main__":
    # No window is created. Use native font discovery (Windows' offscreen plugin
    # has no system fonts and would silently render square placeholders).
    app = QGuiApplication(["dmg-artwork"])
    print(render_background())
