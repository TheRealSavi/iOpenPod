"""Shared clipped popup motion for panels anchored above or below a trigger."""

from enum import Enum

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QFrame, QStyle, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

POPUP_OVERSHOOT_INSET = LAYOUT.space_md
_POPUP_ENTER_MS = 280
_POPUP_EXIT_MS = 190


class PopupDirection(Enum):
    UP = "up"
    DOWN = "down"


class AnimatedPopup(QFrame):
    """Animate a supplied surface inside a stationary, transparent popup window."""

    dismissed = Signal()

    def __init__(
        self, trigger: QWidget, surface: QFrame, *, direction: PopupDirection
    ) -> None:
        super().__init__(
            trigger, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.direction = direction
        self.surface = surface
        surface.setParent(self)
        self._pressed_trigger = False
        self._target_open = False
        self._finalizing_close = False
        self.animation = QPropertyAnimation(surface, b"pos", self)
        self.animation.finished.connect(self._animation_finished)

    @property
    def is_open(self) -> bool:
        """Whether the panel is opening or open, rather than sliding closed."""

        return self._target_open

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.surface.resize(
            event.size().width(), max(1, event.size().height() - POPUP_OVERSHOOT_INSET)
        )

    def _rest_position(self) -> QPoint:
        return QPoint(
            0, POPUP_OVERSHOOT_INSET if self.direction is PopupDirection.UP else 0
        )

    def _hidden_position(self) -> QPoint:
        return QPoint(
            0,
            self.height()
            if self.direction is PopupDirection.UP
            else -self.surface.height(),
        )

    def open_at(self, host_pos: QPoint) -> None:
        self.animation.stop()
        # A hidden widget can defer resizeEvent until show(). Establish the full
        # travel distance before positioning the surface outside the clip.
        self.surface.resize(self.width(), max(1, self.height() - POPUP_OVERSHOOT_INSET))
        self._target_open = True
        self.move(host_pos)
        if not self.isVisible():
            self.surface.move(
                self._hidden_position()
                if self._animations_enabled()
                else self._rest_position()
            )
            self.show()
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(0.8)
        self._animate_to(self._rest_position(), _POPUP_ENTER_MS, curve)

    def toggle(self) -> None:
        if self._target_open:
            self.close()
        else:
            self.open_at(self.pos())

    def dismiss(self) -> None:
        """Discard the panel immediately when its owning context is replaced."""

        self.animation.stop()
        self._target_open = False
        self._finalizing_close = True
        self.close()
        self._finalizing_close = False
        self.surface.move(self._rest_position())

    def _animations_enabled(self) -> bool:
        return bool(
            self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, self)
        )

    def _animate_to(
        self, target: QPoint, duration_ms: int, curve: QEasingCurve
    ) -> None:
        current = self.surface.pos()
        if current == target or not self._animations_enabled():
            self.surface.move(target)
            self._animation_finished()
            return
        self.animation.setDuration(
            max(
                1,
                min(
                    duration_ms,
                    round(
                        duration_ms
                        * abs(target.y() - current.y())
                        / self.surface.height()
                    ),
                ),
            )
        )
        self.animation.setEasingCurve(curve)
        self.animation.setStartValue(current)
        self.animation.setEndValue(target)
        self.animation.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._finalizing_close or not self.isVisible():
            super().closeEvent(event)
            return
        if not self._target_open:
            event.ignore()
            return
        self._target_open = False
        self.animation.stop()
        if (
            not self._animations_enabled()
            or self.surface.pos() == self._hidden_position()
        ):
            # Accept this close directly. Closing again from a synchronous
            # finished handler would reenter an ignored closeEvent.
            super().closeEvent(event)
            return
        event.ignore()
        self._animate_to(
            self._hidden_position(),
            _POPUP_EXIT_MS,
            QEasingCurve(QEasingCurve.Type.InCubic),
        )

    def _animation_finished(self) -> None:
        if self._target_open:
            self.surface.move(self._rest_position())
        else:
            self.dismiss()

    def hideEvent(self, event: QHideEvent) -> None:
        self.animation.stop()
        self._target_open = False
        self._pressed_trigger = False
        self.surface.move(self._rest_position())
        super().hideEvent(event)
        self.dismissed.emit()

    def _over_trigger(self, event: QMouseEvent) -> bool:
        trigger = self.parentWidget()
        return trigger is not None and trigger.rect().contains(
            trigger.mapFromGlobal(event.globalPosition().toPoint())
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed_trigger = False
        if event.button() == Qt.MouseButton.LeftButton and self._over_trigger(event):
            # Hold the popup's grab until release so this click cannot reopen it.
            self._pressed_trigger = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed_trigger and event.button() == Qt.MouseButton.LeftButton:
            self._pressed_trigger = False
            if self._over_trigger(event):
                self.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)
