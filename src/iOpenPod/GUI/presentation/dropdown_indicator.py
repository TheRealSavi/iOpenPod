"""The shared, palette-aware chevron for native dropdown controls."""

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget


def paint_dropdown_indicator(
    widget: QWidget, rect: QRect, *, expanded: bool, enabled: bool = True
) -> None:
    if rect.isEmpty():
        return
    group = (
        QPalette.ColorGroup.Active
        if widget.isEnabled() and enabled
        else QPalette.ColorGroup.Disabled
    )
    role = (
        QPalette.ColorRole.Accent
        if widget.isEnabled() and enabled and (widget.hasFocus() or expanded)
        else QPalette.ColorRole.ButtonText
    )
    center = rect.center()
    direction = -1.0 if expanded else 1.0
    path = QPainterPath(QPointF(center.x() - 5.0, center.y() - direction * 2.5))
    path.lineTo(QPointF(center.x(), center.y() + direction * 2.5))
    path.lineTo(QPointF(center.x() + 5.0, center.y() - direction * 2.5))
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(widget.palette().color(group, role))
    pen.setWidthF(1.75)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
