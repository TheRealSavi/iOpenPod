"""Aspect-preserving Photo painting shared by cards and the inspector."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens


def paint_photo_pixmap(
    painter: QPainter,
    rect: QRectF,
    pixmap: QPixmap,
    tokens: ThemeTokens,
    radius: float,
) -> None:
    """Letterbox one Photo within ``rect`` while retaining its aspect ratio."""

    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    source = QRectF(pixmap.rect())
    if source.isEmpty():
        return
    scale = min(rect.width() / source.width(), rect.height() / source.height())
    width = source.width() * scale
    height = source.height() * scale
    target = QRectF(
        rect.left() + (rect.width() - width) / 2.0,
        rect.top() + (rect.height() - height) / 2.0,
        width,
        height,
    )

    painter.save()
    painter.setClipPath(clip)
    painter.fillRect(rect, QColor(tokens.surface_alt))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(target, pixmap, source)
    painter.restore()

    border = QPen(QColor(tokens.border))
    border.setWidthF(1.0)
    painter.setPen(border)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)


__all__ = ["paint_photo_pixmap"]
