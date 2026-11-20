"""Shared symbolic Mix artwork for the chooser and on-demand device covers."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer

from iOpenPod.GUI.presentation.theme.dynamic import (
    GeniusArtworkColors,
    genius_artwork_colors,
)
from iOpenPod.GUI.presentation.theme.tokens import DARK_TOKENS, ThemeTokens
from iPodDB.library import ArtworkPixels

_COLORS = {
    "rock": 3,
    "alternative": 1,
    "pop": 2,
    "hard-rock": 0,
    "metal": 4,
    "punk": 3,
    "electronic": 0,
    "dance": 3,
    "hip-hop": 2,
    "soul": 4,
    "jazz": 0,
    "blues": 5,
    "country": 2,
    "folk": 1,
    "classical": 4,
    "reggae": 1,
    "latin": 3,
    "soundtracks": 5,
    "focus": 0,
    "love": 3,
    "energy": 2,
    "relax": 4,
}


def mix_colors(key: str, tokens: ThemeTokens) -> GeniusArtworkColors:
    accents = (
        tokens.artwork_blue,
        tokens.artwork_green,
        tokens.artwork_gold,
        tokens.artwork_coral,
        tokens.artwork_violet,
        tokens.artwork_slate,
    )
    return genius_artwork_colors(accents[_COLORS[key]], tokens)


@lru_cache(maxsize=128)
def _glyph(key: str, ink: str) -> bytes:
    if key not in _COLORS:
        raise ValueError("Unknown Genius Mix artwork")
    path = (
        Path(__file__).parents[2] / "assets" / "glyphs" / "genius-mixes" / f"{key}.svg"
    )
    return path.read_bytes().replace(b"currentColor", ink.encode("ascii"))


def paint_mix_artwork(
    painter: QPainter,
    rect: QRectF,
    key: str,
    tokens: ThemeTokens,
    *,
    enabled: bool = True,
) -> None:
    colors = mix_colors(key, tokens)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(rect, colors.field if enabled else QColor(tokens.surface_alt))
    painter.translate(rect.center())
    scale = min(rect.width(), rect.height()) / 176
    painter.scale(scale, scale)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(colors.line if enabled else QColor(tokens.border), 1))
    for diameter in (112, 140, 168):
        orbit = QRectF(-diameter / 2, -diameter / 2, diameter, diameter)
        painter.drawArc(orbit, 25 * 16, 130 * 16)
        painter.drawArc(orbit, 205 * 16, 130 * 16)
    ink = colors.ink if enabled else QColor(tokens.text_disabled)
    raw = _glyph(key, ink.name())
    QSvgRenderer(QByteArray(raw)).render(painter, QRectF(-40, -40, 80, 80))
    painter.restore()


def render_mix_cover(key: str, size: int = 142) -> ArtworkPixels:
    """Render owned RGB bytes on the calling worker, without a widget or disk cache.

    Every call owns its QImage, painter and SVG renderer. No Qt object crosses the
    application seam, and only the small existing SVG source cache is retained.
    """
    if key not in _COLORS:
        raise ValueError("Unknown Genius Mix cover")
    if size not in (142, 240):
        raise ValueError("Unsupported Genius Mix cover size")
    image = QImage(size, size, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    try:
        paint_mix_artwork(painter, QRectF(0, 0, size, size), key, DARK_TOKENS)
    finally:
        painter.end()
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    data = bytes(rgb.constBits())
    # RGB888 rows may contain alignment padding (142 pixels needs two bytes).
    pixels = b"".join(
        data[row * rgb.bytesPerLine() : row * rgb.bytesPerLine() + size * 3]
        for row in range(size)
    )
    return ArtworkPixels(size, size, pixels)
