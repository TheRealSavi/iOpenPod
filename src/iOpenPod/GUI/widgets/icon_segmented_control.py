"""Compact icon-only selectors with the Settings scope switcher's treatment."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QKeyEvent, QPainter, QPaintEvent, QPalette, QPen, QShowEvent
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import IconButton


class _Selector(QWidget):
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        fill = self.palette().color(QPalette.ColorRole.Highlight)
        fill.setAlpha(42)
        painter.setPen(QPen(accent, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)


class IconSegmentedControl(QWidget):
    """Group native icon buttons behind one smoothly moving selection."""

    def __init__(
        self,
        buttons: tuple[IconButton, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buttons = buttons
        self._selector = _Selector(self)
        self._selector.setObjectName("iconSegmentSelector")
        self._selector.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._animation = QPropertyAnimation(self._selector, b"geometry", self)
        self._animation.setDuration(LAYOUT.selection_group_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        size = LAYOUT.control_height_compact
        self.setFixedSize(size * len(buttons) + 4, size + 4)
        for button in buttons:
            button.setParent(self)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setFixedSize(size, size)
            button.setStyleSheet(
                "QToolButton { background: transparent; border: 1px solid transparent; "
                "border-radius: 8px; padding: 0px; }"
                "QToolButton:checked, QToolButton:hover, QToolButton:pressed "
                "{ background: transparent; }"
                "QToolButton:focus { border: 1px dotted palette(highlight); }"
            )
            button.installEventFilter(self)
            self._group.addButton(button)
            layout.addWidget(button)
        buttons[0].setChecked(True)
        self._group.buttonToggled.connect(self._selection_changed)

    def _selection_changed(self, button: IconButton, checked: bool) -> None:
        if checked:
            self.sync_selection()

    def sync_selection(self, *, animate: bool = True) -> None:
        """Follow checked state, including changes made with signals blocked."""
        button = self._group.checkedButton()
        if button is None:
            return
        self._animation.stop()
        target = button.geometry()
        if animate and self.isVisible() and target != self._selector.geometry():
            self._animation.setStartValue(self._selector.geometry())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._selector.setGeometry(target)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            keys = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End)
            if event.key() in keys and isinstance(watched, IconButton):
                index = self._buttons.index(watched)
                if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
                    index = (
                        0 if event.key() == Qt.Key.Key_Home else len(self._buttons) - 1
                    )
                else:
                    step = 1 if event.key() == Qt.Key.Key_Right else -1
                    if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                        step = -step
                    index = max(0, min(len(self._buttons) - 1, index + step))
                button = self._buttons[index]
                if button.isEnabled():
                    button.setFocus()
                    button.click()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.sync_selection(animate=False)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LayoutDirectionChange:
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self.sync_selection(animate=False)
        elif event.type() == QEvent.Type.PaletteChange:
            self._selector.update()
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1.5))
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)
