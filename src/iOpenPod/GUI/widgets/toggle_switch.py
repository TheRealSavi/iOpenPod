"""Compact two-state switch with standard Qt checkbox interaction."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QPoint,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
)
from PySide6.QtGui import QHideEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QCheckBox, QWidget

from iOpenPod.GUI.presentation.motion import MOTION, SpringAnimation, animations_enabled
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_TRACK_WIDTH = 42
_TRACK_HEIGHT = 24
_THUMB_INSET = 3
_FOCUS_GAP = 3


class ToggleSwitch(QCheckBox):
    """Use a sliding-style thumb to show the state without relying on color."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._slide = SpringAnimation(self)
        self._slide.valueChanged.connect(self._repaint_on_slide)
        self.toggled.connect(self._slide_thumb)

    def _repaint_on_slide(self, _value: object) -> None:
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_TRACK_WIDTH + LAYOUT.space_sm, LAYOUT.control_height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_value(self, checked: bool) -> None:
        """Reflect a stored value without emitting an edit."""
        if checked != self.isChecked():
            self._slide.stop()
            with QSignalBlocker(self):
                self.setChecked(checked)

    def _thumb_position(self, fallback: bool) -> float:
        if self._slide.state() != QAbstractAnimation.State.Stopped:
            return float(self._slide.currentValue())
        return float(fallback)

    def _slide_thumb(self, checked: bool) -> None:
        start = self._thumb_position(not checked)
        if self.isVisible() and animations_enabled(self):
            self._slide.retarget(start, float(checked), MOTION.control_ms)
        else:
            self._slide.stop()
        self.update()

    def hideEvent(self, event: QHideEvent) -> None:
        self._slide.stop()
        super().hideEvent(event)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        palette = self.palette()
        role = QPalette.ColorRole
        checked = self.isChecked()
        enabled = self.isEnabled()
        if not enabled:
            fill, edge, thumb = role.AlternateBase, role.Mid, role.ButtonText
        elif checked:
            fill = role.LinkVisited if self.isDown() else role.Highlight
            edge, thumb = fill, role.HighlightedText
        else:
            fill = role.Dark if self.isDown() else role.AlternateBase
            edge = role.ButtonText if self.underMouse() else role.PlaceholderText
            thumb = edge

        track = QRectF(0, 0, _TRACK_WIDTH, _TRACK_HEIGHT)
        track.moveCenter(QRectF(self.rect()).center())
        radius = track.height() / 2
        thumb_radius = radius - _THUMB_INSET
        position = self._thumb_position(checked)
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            position = 1.0 - position
        center_x = track.left() + radius + position * (track.width() - track.height())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if enabled and self.hasFocus():
            ring = track.adjusted(-_FOCUS_GAP, -_FOCUS_GAP, _FOCUS_GAP, _FOCUS_GAP)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette.color(role.Link), 2))
            painter.drawRoundedRect(ring, radius + _FOCUS_GAP, radius + _FOCUS_GAP)
        painter.setBrush(palette.color(fill))
        painter.setPen(QPen(palette.color(edge)))
        painter.drawRoundedRect(track, radius, radius)
        painter.setBrush(palette.color(thumb))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QPointF(center_x, track.center().y()), thumb_radius, thumb_radius
        )
        painter.end()
