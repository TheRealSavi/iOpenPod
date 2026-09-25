"""DPR-aware presentation of packaged iPod product images."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

_IMAGE_DIRECTORY = Path(__file__).parents[2] / "assets" / "ipod_images"
_FALLBACK_IMAGE = "iPodGeneric.png"


def device_icon(
    image_name: str,
    logical_size: int,
    device_pixel_ratio: float = 1.0,
) -> QIcon:
    """Return an icon with enough raster variants for fractional and Retina DPRs."""

    requested_dpr = max(1.0, float(device_pixel_ratio))
    safe_name = _available_image_name(image_name)
    icon = QIcon()
    for dpr in sorted({1.0, 1.5, 2.0, 3.0, round(requested_dpr, 2)}):
        icon.addPixmap(_cached_device_pixmap(safe_name, logical_size, dpr))
    return icon


def device_pixmap(
    image_name: str,
    logical_size: int,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Render one product image for a QLabel at a specific screen DPR."""

    safe_name = _available_image_name(image_name)
    return _cached_device_pixmap(
        safe_name,
        logical_size,
        max(1.0, round(float(device_pixel_ratio), 2)),
    )


def _available_image_name(image_name: str) -> str:
    candidate = Path(image_name)
    if (
        candidate.name == image_name
        and candidate.suffix.casefold() == ".png"
        and (_IMAGE_DIRECTORY / candidate.name).is_file()
    ):
        return candidate.name
    return _FALLBACK_IMAGE


@lru_cache(maxsize=256)
def _cached_device_pixmap(
    image_name: str,
    logical_size: int,
    device_pixel_ratio: float,
) -> QPixmap:
    physical_size = max(1, round(max(1, logical_size) * device_pixel_ratio))
    source = QPixmap(str(_IMAGE_DIRECTORY / image_name))
    canvas = QPixmap(QSize(physical_size, physical_size))
    canvas.fill(Qt.GlobalColor.transparent)
    if not source.isNull():
        scaled = source.scaled(
            QSize(physical_size, physical_size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(canvas)
        painter.drawPixmap(
            (physical_size - scaled.width()) // 2,
            (physical_size - scaled.height()) // 2,
            scaled,
        )
        painter.end()
    canvas.setDevicePixelRatio(device_pixel_ratio)
    return canvas


__all__ = ["device_icon", "device_pixmap"]
