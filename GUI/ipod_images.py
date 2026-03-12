"""
iPod product image resolver.

Thin wrapper around ``ipod_models.resolve_image_filename()`` that returns
a Qt ``QPixmap``.  All data tables (COLOR_MAP, FAMILY_FALLBACK, etc.) live
in the project-root ``ipod_models`` module — this file only handles the
PyQt6 pixmap loading and caching.
"""

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ipod_models import resolve_image_filename, GENERIC_IMAGE

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IMAGE_DIR = _PROJECT_ROOT / "assets" / "ipod_images"


@lru_cache(maxsize=128)
def _get_ipod_image_cached(
    family: str,
    generation: str,
    size: int,
    color: str,
    dpr: float,
) -> QPixmap:
    """Internal cached loader — includes dpr in cache key."""
    filename = resolve_image_filename(family, generation, color)
    path = _IMAGE_DIR / filename
    if not path.exists():
        path = _IMAGE_DIR / GENERIC_IMAGE

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QPixmap()

    phys = round(size * dpr)
    pixmap = pixmap.scaled(
        phys, phys,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def get_ipod_image(
    family: str,
    generation: str,
    size: int = 80,
    color: str = "",
) -> QPixmap:
    """
    Return a scaled QPixmap of the iPod product image.

    Lookup priority:
      1. Exact (family, generation, color) match
      2. Inferred default ("silver" / "white") for that generation
      3. Family-level fallback
      4. iPodGeneric.png

    Args:
        family:     Product line, e.g. "iPod Classic", "iPod Nano"
        generation: e.g. "2nd Gen", "5.5th Gen"
        size:       Maximum dimension (keeps aspect ratio)
        color:      e.g. "Black", "Silver", "Blue" (optional)

    Returns:
        QPixmap scaled to fit within sizexsize (HiDPI-aware).
    """
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    dpr = app.primaryScreen().devicePixelRatio() if app and app.primaryScreen() else 1.0
    return _get_ipod_image_cached(family, generation, size, color, dpr)
