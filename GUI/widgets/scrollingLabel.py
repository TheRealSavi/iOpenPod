from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, QAbstractAnimation
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPainter, QFontMetrics


class ScrollingLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._offset = 0
        self.animation = None
        self.setToolTip(text)

    def getOffset(self):
        return self._offset

    def setOffset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(int, fget=getOffset, fset=setOffset)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            draw_rect = self.rect()
            draw_rect.setWidth(full_width)
            draw_rect.translate(-self._offset, 0)
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignVCenter, self.text())
        else:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignVCenter, self.text())

    def enterEvent(self, event):
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            scroll_distance = full_width - self.width()
            scroll_speed = 0.05  # Adjust speed: pixels per millisecond

            duration = int(scroll_distance / scroll_speed)  # Compute duration

            if self.animation is not None and self.animation.state() == QAbstractAnimation.State.Running:
                self.animation.stop()
            self.animation = QPropertyAnimation(self, b"offset")
            self.animation.setDuration(duration)
            self.animation.setStartValue(0)
            self.animation.setEndValue(scroll_distance)
            self.animation.setLoopCount(-1)
            self.animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.animation is not None:
            self.animation.stop()
            self.setOffset(0)
            super().leaveEvent(event)
