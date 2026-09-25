"""Palette-aware SVG glyph rendering for QWidget controls."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_GLYPH_DIRECTORY = Path(__file__).parents[2] / "assets" / "glyphs"


def glyph_icon(
    name: str,
    logical_size: int,
    color: QColor,
    device_pixel_ratio: float = 1.0,
) -> QIcon:
    """Render one Original-informed glyph as a DPR-aware monochrome icon."""

    requested_dpr = max(1.0, float(device_pixel_ratio))
    color_name = color.name(QColor.NameFormat.HexRgb)
    icon = QIcon()
    for dpr in sorted({1.0, 1.5, 2.0, 3.0, round(requested_dpr, 2)}):
        icon.addPixmap(_glyph_pixmap(name, logical_size, color_name, dpr))
    return icon


@lru_cache(maxsize=512)
def _glyph_pixmap(
    name: str,
    logical_size: int,
    color_name: str,
    device_pixel_ratio: float,
) -> QPixmap:
    path = _GLYPH_DIRECTORY / f"{name}.svg"
    physical_size = max(1, round(logical_size * device_pixel_ratio))
    pixmap = QPixmap(QSize(physical_size, physical_size))
    pixmap.fill(Qt.GlobalColor.transparent)
    if not path.is_file():
        pixmap.setDevicePixelRatio(device_pixel_ratio)
        return pixmap

    raw = path.read_bytes().replace(b"currentColor", color_name.encode("ascii"))
    renderer = QSvgRenderer(QByteArray(raw))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, physical_size, physical_size))
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
