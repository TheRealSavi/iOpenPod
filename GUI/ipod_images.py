"""
iPod product image resolver.

Maps iPod model families and generations to product photos stored in
assets/ipod_images/. Falls back to a silhouette icon if no image matches.
"""

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

# Root of the project (parent of GUI/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IMAGE_DIR = _PROJECT_ROOT / "assets" / "ipod_images"

# Maps (product_line_lower, generation_lower) → image filename.
# Multiple dict entries can share the same image when a single photo
# represents the whole generation (different colors, same body).
_IMAGE_MAP: dict[tuple[str, str], str] = {
    # iPod (full-size, 1G–4G)
    ("ipod", "1st gen"): "ipod_1g.jpg",
    ("ipod", "2nd gen"): "ipod_2g.jpg",
    ("ipod", "3rd gen"): "ipod_3g.jpg",
    ("ipod", "4th gen"): "ipod_4g.jpg",
    ("ipod u2", "4th gen"): "ipod_u2_4g.jpg",

    # iPod Photo
    ("ipod photo", "4th gen"): "ipod_photo_4g.jpg",

    # iPod Video
    ("ipod video", "5th gen"): "ipod_video_5g.jpg",
    ("ipod video", "5.5th gen"): "ipod_video_5_5g.jpg",
    ("ipod video u2", "5th gen"): "ipod_video_u2_5g.jpg",
    ("ipod video u2", "5.5th gen"): "ipod_video_u2_5_5g.jpg",

    # iPod Classic
    ("ipod classic", "1st gen"): "ipod_classic_1g.jpg",
    ("ipod classic", "2nd gen"): "ipod_classic_2g.jpg",
    ("ipod classic", "3rd gen"): "ipod_classic_3g.jpg",

    # iPod Mini
    ("ipod mini", "1st gen"): "ipod_mini_1g.jpg",
    ("ipod mini", "2nd gen"): "ipod_mini_2g.jpg",

    # iPod Nano
    ("ipod nano", "1st gen"): "ipod_nano_1g.jpg",
    ("ipod nano", "2nd gen"): "ipod_nano_2g.jpg",
    ("ipod nano", "3rd gen"): "ipod_nano_3g.jpg",
    ("ipod nano", "4th gen"): "ipod_nano_4g.jpg",
    ("ipod nano", "5th gen"): "ipod_nano_5g.jpg",
    ("ipod nano", "6th gen"): "ipod_nano_6g.jpg",
    ("ipod nano", "7th gen"): "ipod_nano_7g.jpg",

    # iPod Shuffle
    ("ipod shuffle", "1st gen"): "ipod_shuffle_1g.jpg",
    ("ipod shuffle", "2nd gen"): "ipod_shuffle_2g.jpg",
    ("ipod shuffle", "3rd gen"): "ipod_shuffle_3g.jpg",
    ("ipod shuffle", "4th gen"): "ipod_shuffle_4g.jpg",
}

# Fallback chain: if an exact (family, gen) isn't found, try these
# simplified family keys (returns a representative image for that line).
_FAMILY_FALLBACK: dict[str, str] = {
    "ipod": "ipod_4g.jpg",
    "ipod u2": "ipod_u2_4g.jpg",
    "ipod photo": "ipod_photo_4g.jpg",
    "ipod video": "ipod_video_5g.jpg",
    "ipod video u2": "ipod_video_u2_5g.jpg",
    "ipod classic": "ipod_classic_2g.jpg",
    "ipod mini": "ipod_mini_1g.jpg",
    "ipod nano": "ipod_nano_4g.jpg",
    "ipod shuffle": "ipod_shuffle_4g.jpg",
}


@lru_cache(maxsize=64)
def get_ipod_image(family: str, generation: str, size: int = 80) -> QPixmap | None:
    """
    Return a scaled QPixmap of the iPod product photo.

    Args:
        family: Product line, e.g. "iPod Classic", "iPod Nano"
        generation: e.g. "2nd Gen", "5.5th Gen"
        size: Maximum dimension (keeps aspect ratio)

    Returns:
        QPixmap scaled to fit within size×size, or None if no image found.
    """
    key = (family.lower(), generation.lower())
    filename = _IMAGE_MAP.get(key)

    # Fallback to family-level image
    if not filename:
        filename = _FAMILY_FALLBACK.get(family.lower())

    if not filename:
        return None

    path = _IMAGE_DIR / filename
    if not path.exists():
        return None

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None

    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def get_ipod_image_path(family: str, generation: str) -> str | None:
    """
    Return the filesystem path to the iPod product image, or None.

    Useful when you need the path rather than a QPixmap (e.g. for QSS).
    """
    key = (family.lower(), generation.lower())
    filename = _IMAGE_MAP.get(key)
    if not filename:
        filename = _FAMILY_FALLBACK.get(family.lower())
    if not filename:
        return None
    path = _IMAGE_DIR / filename
    return str(path) if path.exists() else None
