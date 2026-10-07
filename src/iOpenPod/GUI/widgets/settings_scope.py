"""Accessible Host/iPod selector with a sliding, palette-aware selection."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


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


class SettingsScopeSwitcher(QWidget):
    """Two native checkable buttons keep keyboard and screen-reader semantics."""

    deviceSelected = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsScopeSwitcher")
        self.setFixedSize(280, LAYOUT.control_height_large)
        self._selector = _Selector(self)
        self._selector.setObjectName("settingsScopeSelector")
        self._selector.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._animation = QPropertyAnimation(self._selector, b"geometry", self)
        self._animation.setDuration(LAYOUT.selection_group_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._host = QPushButton(self)
        self._host.setObjectName("hostSettingsButton")
        self._device = QPushButton(self)
        self._device.setObjectName("ipodSettingsButton")
        self._buttons = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        for index, button in enumerate((self._host, self._device)):
            button.setCheckable(True)
            button.setFlat(True)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(22, 22))
            button.setFixedHeight(LAYOUT.control_height)
            button.setStyleSheet(
                "QPushButton { background: transparent; border: 1px solid transparent; "
                "border-radius: 8px; min-height: 0px; padding: 0px 10px; }"
                "QPushButton:focus { border: 1px dotted palette(highlight); }"
                "QPushButton:checked { font-weight: 600; }"
            )
            button.installEventFilter(self)
            self._buttons.addButton(button, index)
            layout.addWidget(button, 1)
        self._host.setChecked(True)
        self._buttons.idClicked.connect(self._clicked)
        self.retranslate_ui()
        self._update_icons()

    @property
    def device_selected(self) -> bool:
        return self._device.isChecked()

    def select_device(self, selected: bool) -> None:
        if selected == self.device_selected:
            return
        (self._device if selected else self._host).setChecked(True)
        self._move_selector(animate=True)
        self.deviceSelected.emit(selected)

    def _clicked(self, index: int) -> None:
        self._move_selector(animate=True)
        self.deviceSelected.emit(index == 1)

    def _move_selector(self, *, animate: bool) -> None:
        self._animation.stop()
        target = (self._device if self.device_selected else self._host).geometry()
        if animate and self.isVisible():
            self._animation.setStartValue(self._selector.geometry())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._selector.setGeometry(target)

    def retranslate_ui(self) -> None:
        self.setAccessibleName(self.tr("Settings scope"))
        self._host.setText(self.tr("Host"))
        self._host.setAccessibleName(self.tr("Host settings — global defaults"))
        self._host.setToolTip(self.tr("Global defaults on this computer"))
        self._device.setText(self.tr("iPod"))
        self._device.setAccessibleName(self.tr("iPod settings — device overrides"))
        self._device.setToolTip(self.tr("Overrides saved on the Active iPod"))

    def _update_icons(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        for button, name in ((self._host, "monitor"), (self._device, "ipod")):
            button.setIcon(glyph_icon(name, 22, color, self.devicePixelRatioF()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key()
            in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Home,
                Qt.Key.Key_End,
            )
        ):
            selected = event.key() in (Qt.Key.Key_Right, Qt.Key.Key_End)
            if (
                self.layoutDirection() == Qt.LayoutDirection.RightToLeft
                and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            ):
                selected = not selected
            self.select_device(selected)
            (self._device if selected else self._host).setFocus()
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self._move_selector(animate=False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._move_selector(animate=False)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._update_icons()
            self._selector.update()
        elif event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1.5))
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)
