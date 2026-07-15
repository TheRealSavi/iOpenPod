"""
iPod product image resolver.

Thin Qt wrapper that returns a ``QPixmap``. Product image filename resolution
lives in app-core so GUI modules do not import the iPod device package.
"""

from functools import lru_cache

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from iopenpod.application.device_identity import (
    generic_ipod_image_filename,
    resolve_ipod_product_image_filename,
)
from iopenpod.resources import resource_path

from .hidpi import scale_pixmap_for_display

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_IMAGE_DIR = resource_path("assets", "ipod_images")


@lru_cache(maxsize=128)
def get_ipod_image(
    family: str,
    generation: str,
    size: int = 80,
    color: str = "",
) -> QPixmap:
    """
    Return a  QPixmap of the iPod product image.

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
        QPixmap  to fit within sizexsize.
    """
    filename = resolve_ipod_product_image_filename(family, generation, color)
    path = _IMAGE_DIR / filename
    if not path.exists():
        path = _IMAGE_DIR / generic_ipod_image_filename()

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QPixmap()  # Return empty pixmap if loading failed

    return scale_pixmap_for_display(
        pixmap,
        size,
        size,
        aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
        transform_mode=Qt.TransformationMode.SmoothTransformation,
    )
