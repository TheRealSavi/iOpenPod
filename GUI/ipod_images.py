"""
iPod product image resolver.

Thin wrapper around ``ipod_models.resolve_image_filename()`` that returns
a Qt ``QPixmap``.  All data tables (COLOR_MAP, FAMILY_FALLBACK, etc.) live
in the project-root ``ipod_models`` module — this file only handles the
PyQt6 pixmap loading and caching.
"""

from functools import lru_cache
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from ipod_models import resolve_image_filename, GENERIC_IMAGE
from GUI import PROJECT_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_IMAGE_DIR = PROJECT_ROOT / "assets" / "ipod_images"


@lru_cache(maxsize=128)
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
        QPixmap scaled to fit within sizexsize.
    """
    filename = resolve_image_filename(family, generation, color)
    path = _IMAGE_DIR / filename
    if not path.exists():
        path = _IMAGE_DIR / GENERIC_IMAGE

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QPixmap()  # Return empty pixmap if loading failed

    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
