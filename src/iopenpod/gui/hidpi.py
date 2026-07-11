from __future__ import annotations

from math import ceil
from typing import Any, cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QPixmap


def effective_device_pixel_ratio(widget: Any | None = None) -> float:
    """Return the best available device pixel ratio for rendering."""
    if widget is not None:
        try:
            dpr = float(widget.devicePixelRatioF())
            if dpr >= 1.0:
                return dpr
        except Exception:
            pass

        try:
            screen = widget.screen()
            if screen is not None:
                dpr = float(screen.devicePixelRatio())
                if dpr >= 1.0:
                    return dpr
        except Exception:
            pass

        try:
            window = widget.window().windowHandle()
            if window is not None and window.screen() is not None:
                dpr = float(window.screen().devicePixelRatio())
                if dpr >= 1.0:
                    return dpr
        except Exception:
            pass

    app = cast(QGuiApplication | None, QGuiApplication.instance())
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            try:
                dpr = float(screen.devicePixelRatio())
                if dpr >= 1.0:
                    return dpr
            except Exception:
                pass

    return 1.0


def logical_to_physical(px: int | float, dpr: float | None = None) -> int:
    """Convert a logical pixel size to a physical pixel size."""
    ratio = max(1.0, dpr if dpr is not None else effective_device_pixel_ratio())
    return max(1, int(ceil(float(px) * ratio)))


def scale_pixmap_for_display(
    pixmap: QPixmap,
    width: int,
    height: int,
    *,
    widget: Any | None = None,
    aspect_mode: Qt.AspectRatioMode = Qt.AspectRatioMode.KeepAspectRatio,
    transform_mode: Qt.TransformationMode = Qt.TransformationMode.SmoothTransformation,
) -> QPixmap:
    """Scale a pixmap to logical size while preserving Retina detail."""
    if pixmap.isNull():
        return QPixmap()

    dpr = effective_device_pixel_ratio(widget)
    scaled = pixmap.scaled(
        logical_to_physical(width, dpr),
        logical_to_physical(height, dpr),
        aspect_mode,
        transform_mode,
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled
