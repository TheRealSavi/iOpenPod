from PyQt6.QtCore import Qt, QPropertyAnimation, QAbstractAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation
from PyQt6.QtCore import pyqtProperty  # type: ignore[attr-defined]
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPainter, QFontMetrics, QEnterEvent


class ScrollingLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._offset = 0
        self.animation_group = None
        self.setToolTip(text)

    def getOffset(self):
        return self._offset

    def setOffset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(int, fget=getOffset, fset=setOffset)

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            draw_rect = self.rect()
            draw_rect.setWidth(full_width)
            draw_rect.translate(-self._offset, 0)
            painter.drawText(
                draw_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text())
        else:
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text())

    def enterEvent(self, event: QEnterEvent | None):
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            scroll_distance = full_width - self.width()
            scroll_speed = 0.025  # pixels per millisecond (slower)
            duration = int(scroll_distance / scroll_speed)
            pause_duration = 1200  # ms to pause at each end

            if self.animation_group is not None and self.animation_group.state() == QAbstractAnimation.State.Running:
                self.animation_group.stop()

            # Create sequential animation: pause -> scroll right -> pause -> scroll left -> loop
            self.animation_group = QSequentialAnimationGroup(self)

            # Initial pause at start
            start_pause = QPauseAnimation(pause_duration)
            self.animation_group.addAnimation(start_pause)

            # Scroll forward (left to right, revealing end of text)
            forward_anim = QPropertyAnimation(self, b"offset")
            forward_anim.setDuration(duration)
            forward_anim.setStartValue(0)
            forward_anim.setEndValue(scroll_distance)
            forward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)  # Gentler easing
            self.animation_group.addAnimation(forward_anim)

            # Pause at end
            end_pause = QPauseAnimation(pause_duration)
            self.animation_group.addAnimation(end_pause)

            # Scroll backward (right to left, back to start)
            backward_anim = QPropertyAnimation(self, b"offset")
            backward_anim.setDuration(duration)
            backward_anim.setStartValue(scroll_distance)
            backward_anim.setEndValue(0)
            backward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)  # Gentler easing
            self.animation_group.addAnimation(backward_anim)

            # Pause at start before looping
            loop_pause = QPauseAnimation(pause_duration)
            self.animation_group.addAnimation(loop_pause)

            self.animation_group.setLoopCount(-1)
            self.animation_group.start()
        super().enterEvent(event)

    def leaveEvent(self, a0):
        if self.animation_group is not None:
            self.animation_group.stop()
            self.setOffset(0)
        super().leaveEvent(a0)
