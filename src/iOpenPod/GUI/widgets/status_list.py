"""Compact status-bar control and a live, keyboard-accessible status popup."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QCloseEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.status import ApplicationStatus, StatusMessage
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.status_controls import StatusControls
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind

# Leave room for the entrance curve's small overshoot above the final panel.
_POPUP_TOP_INSET = LAYOUT.space_md
_POPUP_ENTER_MS = 280
_POPUP_EXIT_MS = 190


class _StatusSurface(QFrame):
    """Paint the rounded panel within the transparent popup viewport."""

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        # Qt replaces a translucent window's own Base color with black.
        palette = QApplication.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
        painter.setBrush(palette.brush(QPalette.ColorRole.Base))
        painter.drawRoundedRect(
            self.rect().adjusted(0, 0, -1, -1),
            LAYOUT.radius_panel,
            LAYOUT.radius_panel,
        )


class _StatusPopup(QFrame):
    """Clip the panel's full-height travel inside a stationary popup window."""

    def __init__(self, trigger: QWidget, flags: Qt.WindowType) -> None:
        super().__init__(trigger, flags)
        self._pressed_trigger = False
        self._target_open = False
        self._finalizing_close = False
        self.surface = _StatusSurface(self)
        self.surface.setObjectName("activeStatusesSurface")
        self._animation = QPropertyAnimation(self.surface, b"pos", self)
        self._animation.setObjectName("activeStatusesAnimation")
        self._animation.finished.connect(self._animation_finished)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.surface.resize(
            event.size().width(), event.size().height() - _POPUP_TOP_INSET
        )

    def open_at(self, host_pos: QPoint) -> None:
        """Reveal the full panel from below the popup's clipped lower edge."""

        self._animation.stop()
        self._target_open = True
        self.move(host_pos)
        if not self.isVisible():
            start = QPoint(0, self.height())
            rest = QPoint(0, _POPUP_TOP_INSET)
            self.surface.move(start if self._animations_enabled() else rest)
            self.show()
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(0.8)
        self._animate_to(QPoint(0, _POPUP_TOP_INSET), _POPUP_ENTER_MS, curve)

    def toggle(self) -> None:
        if self._target_open:
            self.close()
        else:
            self.open_at(self.pos())

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
        duration = max(
            1,
            min(
                duration_ms,
                round(
                    duration_ms * abs(target.y() - current.y()) / self.surface.height()
                ),
            ),
        )
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(curve)
        self._animation.setStartValue(current)
        self._animation.setEndValue(target)
        self._animation.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._finalizing_close or not self.isVisible():
            super().closeEvent(event)
            return
        event.ignore()
        if not self._target_open:
            return
        self._target_open = False
        self._animation.stop()
        self._animate_to(
            QPoint(0, self.height()),
            _POPUP_EXIT_MS,
            QEasingCurve(QEasingCurve.Type.InCubic),
        )

    def _animation_finished(self) -> None:
        if self._target_open:
            self.surface.move(0, _POPUP_TOP_INSET)
            return
        self._finalizing_close = True
        self.close()
        self._finalizing_close = False
        self.surface.move(0, _POPUP_TOP_INSET)

    def _over_trigger(self, event: QMouseEvent) -> bool:
        trigger = self.parentWidget()
        return trigger is not None and trigger.rect().contains(
            trigger.mapFromGlobal(event.globalPosition().toPoint())
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed_trigger = False
        if event.button() == Qt.MouseButton.LeftButton and self._over_trigger(event):
            # Keep the popup's mouse grab until release so the click cannot
            # close the popup and then activate the underlying trigger.
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


class _StatusRow(QWidget):
    """Show one active status with its controls beneath the full message."""

    def __init__(self, status: ApplicationStatus, parent: QWidget) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(
            LAYOUT.space_xs, LAYOUT.space_xs, LAYOUT.space_xs, LAYOUT.space_xs
        )
        layout.setSpacing(LAYOUT.space_xs)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.controls = StatusControls(status, self)
        layout.addWidget(self.controls)

    def set_status(self, value: StatusMessage) -> None:
        self.label.setText(workflow_text(value.message))
        self.setAccessibleName(self.label.text())
        self.controls.set_status(value)

    def size_for_width(self, width: int) -> QSize:
        self.setFixedWidth(width)
        self._layout.activate()
        text_width = max(1, width - 2 * LAYOUT.space_xs)
        text_height = (
            self.label.fontMetrics()
            .boundingRect(
                QRect(0, 0, text_width, 10_000),
                Qt.TextFlag.TextWordWrap,
                self.label.text(),
            )
            .height()
        )
        controls_height = max(
            self.controls.progress.sizeHint().height(),
            self.controls.action.sizeHint().height(),
        )
        height = (
            2 * LAYOUT.space_xs
            + text_height
            + LAYOUT.space_xs
            + controls_height
            + 2 * (LAYOUT.space_sm + LAYOUT.space_3xs)
            + LAYOUT.space_xs
        )
        return QSize(width, height)


class StatusListButton(IconButton):
    """Expose all active messages without giving callers a status-bar widget."""

    def __init__(
        self, status: ApplicationStatus, parent: QWidget | None = None
    ) -> None:
        super().__init__("bell", "", parent, kind=IconButtonKind.SUBTLE)
        self._status = status
        self.setObjectName("activeStatusesButton")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._popup = _StatusPopup(
            self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self._popup.setObjectName("activeStatusesPopup")
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Clicking the trigger again closes the popup instead of reopening it.
        self._popup.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        surface = self._popup.surface
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_sm, LAYOUT.space_md, LAYOUT.space_md
        )
        layout.setSpacing(LAYOUT.space_xs)
        header = QHBoxLayout()
        self._heading = QLabel(surface)
        self._heading.setObjectName("activeStatusesHeading")
        header.addWidget(self._heading, 1)
        self._close = IconButton("x", "", surface, kind=IconButtonKind.SUBTLE)
        self._close.setFixedSize(LAYOUT.space_lg, LAYOUT.space_lg)
        self._close.clicked.connect(self._popup.close)
        header.addWidget(self._close)
        layout.addLayout(header)
        self._list = QListWidget(surface)
        self._list.setObjectName("activeStatusesList")
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self._list)
        self._empty = QLabel(surface)
        self._empty.setObjectName("activeStatusesEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)
        self.clicked.connect(self._toggle_popup)
        status.activeMessagesChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        messages = self._status.active_messages
        sources = {message.source for message in messages}
        # Keep existing items and scroll/selection state during progress updates.
        for row in range(self._list.count() - 1, -1, -1):
            if self._list.item(row).data(Qt.ItemDataRole.UserRole) not in sources:
                self._list.takeItem(row)
        for row, message in enumerate(messages):
            if row >= self._list.count():
                item = QListWidgetItem(self._list)
                item.setData(Qt.ItemDataRole.UserRole, message.source)
            else:
                item = self._list.item(row)
            text = workflow_text(message.message)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            existing = self._list.itemWidget(item)
            if message.progress is not None or message.action is not None:
                item.setText("")
                if not isinstance(existing, _StatusRow):
                    existing = _StatusRow(self._status, self._list)
                    self._list.setItemWidget(item, existing)
                existing.set_status(message)
            else:
                if isinstance(existing, _StatusRow):
                    self._list.removeItemWidget(item)
                    existing.deleteLater()
                    item.setSizeHint(QSize())
                if item.text() != text:
                    item.setText(text)
        self._resize_enhanced_rows()
        self._list.setVisible(bool(messages))
        self._empty.setVisible(not messages)
        self.retranslate_ui()

    def _resize_enhanced_rows(self) -> None:
        width = max(120, self._list.viewport().width() - 2 * LAYOUT.space_xs)
        for index in range(self._list.count()):
            item = self._list.item(index)
            row = self._list.itemWidget(item)
            if isinstance(row, _StatusRow):
                item.setSizeHint(row.size_for_width(width))

    def retranslate_ui(self) -> None:
        count = len(self._status.active_messages)
        name = self.tr("Active statuses (%1)").replace("%1", str(count))
        self.setAccessibleName(name)
        self.setToolTip(name)
        self._popup.setAccessibleName(name)
        self._heading.setText(name)
        self._list.setAccessibleName(self.tr("Active statuses"))
        self._empty.setText(self.tr("No active statuses"))
        self._close.setAccessibleName(self.tr("Close statuses"))
        self._close.setToolTip(self.tr("Close statuses"))
        self.setText(str(count) if count else "")
        self._resize_button()

    def _resize_button(self) -> None:
        height = max(LAYOUT.space_lg, self.fontMetrics().height() + LAYOUT.space_2xs)
        width = height
        if self.text():
            width += self.fontMetrics().horizontalAdvance(self.text()) + LAYOUT.space_xs
        self.setFixedSize(width, height)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        elif event.type() == QEvent.Type.FontChange:
            self._resize_button()
            self._resize_enhanced_rows()

    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.toggle()
            return
        screen = self.screen().availableGeometry()
        popup_width = min(LAYOUT.status_popup_width, screen.width())
        popup_height = min(
            LAYOUT.status_popup_height, max(1, screen.height() - _POPUP_TOP_INSET)
        )
        self._popup.resize(popup_width, popup_height + _POPUP_TOP_INSET)
        anchor = self.mapToGlobal(QPoint(self.width(), 0))
        x = max(
            screen.left(),
            min(
                anchor.x() - popup_width,
                screen.right() - self._popup.width() + 1,
            ),
        )
        y = max(
            screen.top(),
            min(
                anchor.y() - self._popup.height(),
                screen.bottom() - self._popup.height() + 1,
            ),
        )
        self._popup.open_at(QPoint(x, y))
        self._resize_enhanced_rows()
        if self._list.count():
            if self._list.currentRow() < 0:
                self._list.setCurrentRow(0)
            self._list.setFocus(Qt.FocusReason.PopupFocusReason)
        else:
            self._close.setFocus(Qt.FocusReason.PopupFocusReason)
