"""SVG glyph loader for iOpenPod.

Loads 24x24 stroke-based SVG icons from assets/glyphs/, colorizes them by
replacing ``currentColor`` with the requested CSS color, and renders to
QIcon / QPixmap at DPI- sizes via QSvgRenderer.
"""

from __future__ import annotations

import os
import re

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap

from .hidpi import effective_device_pixel_ratio, logical_to_physical

try:
    from PyQt6.QtSvg import QSvgRenderer
    _HAS_SVG = True
except ImportError:
    QSvgRenderer = None
    _HAS_SVG = False

_GLYPH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "glyphs",
)

_svg_cache: dict[str, bytes] = {}

_RE_RGBA = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+(?:\.\d+)?)\s*)?\)"
)


def _parse_color(color: str) -> tuple[str, float]:
    """Convert a CSS color string to ``(hex_rgb, opacity_0_to_1)``."""
    if color.startswith("#"):
        return color, 1.0
    m = _RE_RGBA.match(color)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4)) if m.group(4) else 255.0
        if a > 1.0:
            a /= 255.0
        return f"#{r:02x}{g:02x}{b:02x}", a
    return color, 1.0


def _load_svg(name: str) -> bytes | None:
    if name in _svg_cache:
        return _svg_cache[name]
    path = os.path.join(_GLYPH_DIR, f"{name}.svg")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    _svg_cache[name] = data
    return data


def glyph_pixmap(name: str, size: int, color: str = "#ffffff") -> QPixmap | None:
    """Render a named SVG glyph to a *size x size* ``QPixmap``.

    *color* may be any CSS color (``#hex``, ``rgb()``, ``rgba()``).
    Returns ``None`` when SVG support is unavailable or the file is missing.
    """
    if not _HAS_SVG:
        return None
    raw = _load_svg(name)
    if raw is None:
        return None
    if QSvgRenderer is None:
        return None
    hex_color, opacity = _parse_color(color)
    colored = raw.replace(b"currentColor", hex_color.encode("ascii"))
    if opacity < 0.99:
        colored = colored.replace(
            b"<svg ", f'<svg opacity="{opacity:.3f}" '.encode("ascii"), 1
        )
    renderer = QSvgRenderer(QByteArray(colored))
    if not renderer.isValid():
        return None
    dpr = effective_device_pixel_ratio()
    pixel_size = logical_to_physical(size, dpr)
    px = QPixmap(pixel_size, pixel_size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    renderer.render(painter)
    painter.end()
    px.setDevicePixelRatio(dpr)
    return px


def glyph_icon(name: str, size: int, color: str = "#ffffff") -> QIcon | None:
    """Render a named SVG glyph to a ``QIcon``.

    Returns ``None`` when SVG support is unavailable or the file is missing.
    """
    px = glyph_pixmap(name, size, color)
    if px is None:
        return None
    return QIcon(px)
