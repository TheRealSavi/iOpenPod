"""Native Calendar tabs with a sliding selector and a bounded content swipe."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import QStyle, QStyleOptionTab, QTabBar, QTabWidget, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class _CalendarTabBar(QTabBar):
    """Keep Qt tab semantics while using the Settings scope selector's motion."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setDrawBase(False)
        self._selector = QRectF()
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("calendarTabSelectionSlide")
        self._animation.setDuration(LAYOUT.selection_group_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(self._advance)
        self.currentChanged.connect(lambda: self._move_selector(animate=True))

    def _target(self) -> QRectF:
        inset = LAYOUT.space_2xs
        return QRectF(self.tabRect(self.currentIndex())).adjusted(
            inset, inset, -inset, -inset
        )

    def _move_selector(self, *, animate: bool) -> None:
        self._animation.stop()
        target = self._target()
        if (
            animate
            and self.isVisible()
            and not self._selector.isEmpty()
            and self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, self)
        ):
            self._animation.setStartValue(self._selector)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._selector = target
            self.update()

    def _advance(self, value: object) -> None:
        if isinstance(value, QRectF):
            self._selector = value
            self.update()

    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        if (
            hasattr(self, "_animation")
            and self._animation.state() != QAbstractAnimation.State.Running
        ):
            self._move_selector(animate=False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._move_selector(animate=False)

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if hasattr(self, "_animation") and event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.Resize,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.LanguageChange,
            QEvent.Type.LayoutDirectionChange,
        }:
            self._move_selector(animate=False)
        return result

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1.5))
        painter.setBrush(palette.brush(QPalette.ColorRole.Base))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(1, 1, -1, -1),
            LAYOUT.radius_panel,
            LAYOUT.radius_panel,
        )
        accent = palette.color(QPalette.ColorRole.Highlight)
        fill = palette.color(QPalette.ColorRole.Highlight)
        fill.setAlpha(42)
        painter.setPen(QPen(accent, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(
            self._selector, LAYOUT.radius_control, LAYOUT.radius_control
        )
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            self.style().drawControl(
                QStyle.ControlElement.CE_TabBarTabLabel, option, painter, self
            )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(
                self._target().adjusted(3, 3, -3, -3),
                LAYOUT.radius_control,
                LAYOUT.radius_control,
            )


def _capture(page: QWidget) -> QPixmap:
    """Include the canvas behind transparent gaps without capturing other pages."""
    content = page.grab()
    frame = QPixmap(content.size())
    frame.setDevicePixelRatio(content.devicePixelRatio())
    frame.fill(page.palette().color(QPalette.ColorRole.Window))
    painter = QPainter(frame)
    painter.drawPixmap(0, 0, content)
    painter.end()
    return frame


class _ContentSwipe(QWidget):
    """Slide two viewport snapshots; discard them when live content is revealed."""

    def __init__(self, parent: QTabWidget) -> None:
        super().__init__(parent)
        self._tabs = parent
        self.setObjectName("calendarContentSwipe")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Consume pointer input over moving snapshots. The tab bar stays live,
        # so a reversal remains available without clicking misaligned rows.
        self._outgoing = QPixmap()
        self._incoming = QPixmap()
        self._target: QWidget | None = None
        self._progress = 0.0
        self._direction = 1
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("calendarContentSlide")
        self._animation.setDuration(LAYOUT.calendar_page_slide_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.cancel)
        self._prepare = QTimer(self)
        self._prepare.setSingleShot(True)
        self._prepare.timeout.connect(self._start)
        self.hide()
        parent.installEventFilter(self)

    def begin(self, outgoing: QPixmap, target: QWidget, direction: int) -> None:
        self.cancel()
        self._outgoing = outgoing
        self._target = target
        self._direction = direction
        self._progress = 0.0
        self.setGeometry(QRect(target.mapTo(self._tabs, QPoint()), target.size()))
        self.show()
        self.raise_()
        # The page's currentChanged handlers update its empty state and labels
        # synchronously. Capture their final result before the next paint.
        self._prepare.start(0)

    def _start(self) -> None:
        if self._target is None or not self.isVisible():
            self.cancel()
            return
        self._incoming = _capture(self._target)
        self._animation.start()

    def cancel(self) -> None:
        self._prepare.stop()
        self._animation.stop()
        self.hide()
        self._outgoing = QPixmap()
        self._incoming = QPixmap()
        self._target = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.Resize,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.LanguageChange,
        }:
            self.cancel()
        return False

    def _advance(self, value: object) -> None:
        if isinstance(value, (int, float)):
            self._progress = float(value)
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().brush(QPalette.ColorRole.Window))
        offset = round(self.width() * self._progress) * self._direction
        painter.drawPixmap(offset, 0, self._outgoing)
        painter.drawPixmap(offset - self._direction * self.width(), 0, self._incoming)


class CalendarTabs(QTabWidget):
    """Commit navigation immediately, then swipe the old and new content together."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(_CalendarTabBar(self))
        self._shown_index = -1
        self._swipe = _ContentSwipe(self)
        self.currentChanged.connect(self._changed)

    def cancel_transition(self) -> None:
        self._swipe.cancel()

    def _changed(self, index: int) -> None:
        previous_index = self._shown_index
        previous = self.widget(previous_index)
        current = self.widget(index)
        self._shown_index = index
        if (
            previous is None
            or current is None
            or not self.isVisible()
            or not self.style().styleHint(
                QStyle.StyleHint.SH_Widget_Animate, None, self
            )
        ):
            self._swipe.cancel()
            return
        outgoing = self._swipe.grab() if self._swipe.isVisible() else _capture(previous)
        self._swipe.begin(outgoing, current, 1 if index > previous_index else -1)
