"""Helpers for UI-only artwork presentation effects."""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap


def nested_artwork_radius(
    surface_radius: int,
    inset: int,
    *,
    min_radius: int = 4,
) -> int:
    """Return an artwork radius that visually echoes its containing surface."""

    radius = int(round(float(surface_radius) - (max(0, inset) * 0.4)))
    return max(min_radius, min(surface_radius, radius))


def rounded_artwork_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    """Return a copy of *pixmap* clipped to a rounded rectangle."""

    if pixmap.isNull() or radius <= 0:
        return pixmap

    target = QPixmap(pixmap.size())
    target.setDevicePixelRatio(pixmap.devicePixelRatio())
    target.fill(Qt.GlobalColor.transparent)

    dpr = target.devicePixelRatio()
    rect = QRectF(
        0.0,
        0.0,
        target.width() / dpr,
        target.height() / dpr,
    )

    path = QPainterPath()
    path.addRoundedRect(rect, float(radius), float(radius))

    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return target


def enhance_artwork_image(
    image: Image.Image,
    *,
    enabled: bool = True,
) -> Image.Image:
    """Apply UI-only post-processing to decoded artwork."""

    if not enabled:
        return image

    width, height = image.size
    min_dim = min(width, height)

    if min_dim <= 0:
        return image

    sharpen_percent = 105
    contrast_factor = 1.03
    color_factor = 1.02

    if min_dim <= 80:
        sharpen_percent = 120
        contrast_factor = 1.05
        color_factor = 1.03
    elif min_dim <= 140:
        sharpen_percent = 112
        contrast_factor = 1.04
        color_factor = 1.025

    enhanced = image.filter(
        ImageFilter.UnsharpMask(radius=0.8, percent=sharpen_percent, threshold=3)
    )
    enhanced = ImageEnhance.Contrast(enhanced).enhance(contrast_factor)
    enhanced = ImageEnhance.Color(enhanced).enhance(color_factor)
    return enhanced


def virtual_artwork_payload(
    image: Image.Image,
    *,
    sharpen: bool = True,
) -> tuple[Image.Image, tuple[int, int, int], dict[str, tuple[int, int, int]]]:
    """Return the UI-only enhanced image plus derived display colors."""

    from .imgMaker import get_artwork_colors

    enhanced = enhance_artwork_image(image, enabled=sharpen)
    dominant_color, album_colors = get_artwork_colors(enhanced)
    return enhanced, dominant_color, album_colors
