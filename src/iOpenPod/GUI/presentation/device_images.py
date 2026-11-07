"""DPR-aware presentation of packaged iPod product images."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

from iOpenPod.app.core.device_artwork import device_artwork_path


def device_icon(
    image_name: str,
    logical_size: int,
    device_pixel_ratio: float = 1.0,
    *,
    itunes_107: bool = False,
) -> QIcon:
    """Return an icon with enough raster variants for fractional and Retina DPRs."""

    requested_dpr = max(1.0, float(device_pixel_ratio))
    source_path = device_artwork_path(image_name, itunes_107=itunes_107)
    icon = QIcon()
    for dpr in sorted({1.0, 1.5, 2.0, 3.0, round(requested_dpr, 2)}):
        icon.addPixmap(_cached_device_pixmap(source_path, logical_size, dpr))
    return icon


def device_pixmap(
    image_name: str,
    logical_size: int,
    device_pixel_ratio: float = 1.0,
    *,
    itunes_107: bool = False,
) -> QPixmap:
    """Render one product image for a QLabel at a specific screen DPR."""

    source_path = device_artwork_path(image_name, itunes_107=itunes_107)
    return _cached_device_pixmap(
        source_path,
        logical_size,
        max(1.0, round(float(device_pixel_ratio), 2)),
    )


@lru_cache(maxsize=256)
def _cached_device_pixmap(
    source_path: Path,
    logical_size: int,
    device_pixel_ratio: float,
) -> QPixmap:
    physical_size = max(1, round(max(1, logical_size) * device_pixel_ratio))
    source = QPixmap(str(source_path))
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
