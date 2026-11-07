"""One desktop dropdown lifecycle for action lists and embedded item views.

Highlighting is presentation state; only an explicit activation invokes an action.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCursor,
    QDragMoveEvent,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionToolButton,
    QStylePainter,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class DropdownOpenMode(Enum):
    HOVER = auto()
    KEYBOARD = auto()
    DRAG = auto()


def _property(widget: QWidget, name: str, value: bool) -> None:
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class _ActionRow(QToolButton):
    """Native action semantics, with a separate current-page checkmark."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Keep submenu opening on explicit activation, including a held click.
        QAbstractButton.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        QAbstractButton.mouseReleaseEvent(self, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.features = QStyleOptionToolButton.ToolButtonFeature.None_
        glyph = self.defaultAction().property("dropdownGlyph")
        if isinstance(glyph, str):
            option.icon = glyph_icon(
                glyph,
                LAYOUT.icon_size,
                option.palette.color(QPalette.ColorRole.ButtonText),
                self.devicePixelRatioF(),
            )
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        submenu = isinstance(self.defaultAction().menu(), QMenu)
        if submenu or self.isChecked():
            rect = self.rect().adjusted(
                self.width() - LAYOUT.control_height_compact, 0, -LAYOUT.space_xs, 0
            )
            glyph_icon(
                "chevron-right" if submenu else "check",
                LAYOUT.icon_size,
                self.palette().color(QPalette.ColorRole.ButtonText),
                self.devicePixelRatioF(),
            ).paint(painter, rect)


@dataclass(frozen=True)
class _Target:
    widget: QWidget
    index: QPersistentModelIndex = field(default_factory=QPersistentModelIndex)

    def model_index(self) -> QModelIndex:
        model = self.index.model()
        return (
            model.index(self.index.row(), self.index.column(), self.index.parent())
            if self.index.isValid()
            else QModelIndex()
        )


class HoverDropdown(QFrame):
    """Shared popup surface. Supply actions and optionally one native tree view."""

    aboutToShow = Signal()
    dismissed = Signal()

    def __init__(self, trigger: QPushButton, group: "HoverDropdownGroup") -> None:
        super().__init__(trigger, Qt.WindowType.Popup)
        self.setProperty("hoverDropdown", True)
        self.trigger = trigger
        self.group = group
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(
            LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs
        )
        self.content_layout.setSpacing(LAYOUT.space_3xs)
        self._rows: list[_ActionRow] = []
        self._view: QTreeView | None = None
        self._active: _Target | None = None
        self.setMinimumWidth(210)
        group.add(self)

    def add_item(self, action: QAction) -> QToolButton:
        self.addAction(action)
        row = _ActionRow(self)
        row.setProperty("dropdownItem", True)
        row.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        row.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row.setDefaultAction(action)
        self._rows.append(row)
        self.content_layout.addWidget(row)
        action.changed.connect(lambda: self._refresh_row(row, action))
        action.triggered.connect(lambda: self._invoked(row, action))
        self._refresh_row(row, action)
        return row

    def _refresh_row(self, row: QToolButton, action: QAction) -> None:
        row.setVisible(action.isVisible())
        if self.isVisible():
            if (
                self._active is not None
                and self._active.widget is row
                and (not action.isEnabled() or not action.isVisible())
            ):
                self.highlight_first()
            QTimer.singleShot(0, self, self.fit)

    def _invoked(self, row: QToolButton, action: QAction) -> None:
        menu = action.menu()
        if not isinstance(menu, QMenu):
            self.group.close(restore_focus=True)
        else:
            menu.popup(row.mapToGlobal(QPoint(row.width(), 0)))
            first = next(
                (
                    a
                    for a in menu.actions()
                    if a.isVisible() and a.isEnabled() and not a.isSeparator()
                ),
                None,
            )
            if first is not None:
                menu.setActiveAction(first)

    def set_item_view(self, view: QTreeView) -> None:
        """Register an activation-only tree, laid out by the caller's content."""
        self._view = view
        view.setProperty("dropdownView", True)
        view.selectionModel().currentChanged.connect(self._view_current_changed)

    def _view_current_changed(
        self, current: QModelIndex, _previous: QModelIndex
    ) -> None:
        view = self._view
        if view is not None and view.hasFocus() and current.isValid():
            self._active = _Target(view, QPersistentModelIndex(current))
            for row in self._rows:
                _property(row, "dropdownActive", False)

    def fit(self) -> None:
        self.ensurePolished()
        self.adjustSize()
        self.place()

    def place(self) -> None:
        screen = self.trigger.screen().availableGeometry()
        self.resize(
            min(self.width(), screen.width()), min(self.height(), screen.height())
        )
        position = self.trigger.mapToGlobal(QPoint(0, self.trigger.height()))
        position.setX(
            max(screen.left(), min(position.x(), screen.right() - self.width() + 1))
        )
        if position.y() + self.height() > screen.bottom() + 1:
            position.setY(
                max(
                    screen.top(), self.trigger.mapToGlobal(QPoint()).y() - self.height()
                )
            )
        self.move(position)

    def _targets(self) -> list[_Target]:
        targets = [
            _Target(row) for row in self._rows if not row.isHidden() and row.isEnabled()
        ]
        view = self._view
        if view is not None and not view.isHidden() and view.isEnabled():
            index = view.model().index(0, 0)
            while index.isValid():
                if index.flags() & Qt.ItemFlag.ItemIsEnabled:
                    targets.append(_Target(view, QPersistentModelIndex(index)))
                index = view.indexBelow(index)
        return targets

    def highlight_first(self, *, last: bool = False) -> None:
        targets = self._targets()
        self._highlight(targets[-1 if last else 0] if targets else None)

    def _highlight(self, target: _Target | None, *, focus: bool = True) -> None:
        self._active = target
        for row in self._rows:
            _property(
                row, "dropdownActive", target is not None and target.widget is row
            )
        view = self._view
        if view is not None:
            view.setCurrentIndex(
                target.model_index()
                if target is not None and target.widget is view
                else QModelIndex()
            )
            if target is not None and target.widget is view:
                view.scrollTo(target.index)
        if focus:
            (target.widget if target is not None else self).setFocus(
                Qt.FocusReason.PopupFocusReason
            )

    def point_at(self, position: QPoint) -> None:
        for row in self._rows:
            if (
                row.isVisible()
                and row.isEnabled()
                and row.rect().contains(row.mapFromGlobal(position))
            ):
                self._highlight(_Target(row))
                return
        view = self._view
        if view is not None and view.isVisible():
            index = view.indexAt(view.viewport().mapFromGlobal(position))
            if index.isValid():
                self._highlight(_Target(view, QPersistentModelIndex(index)))

    def navigate(self, key: int) -> bool:
        """Handle content navigation; return false for heading-to-heading keys."""
        targets = self._targets()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            if targets:
                current = targets.index(self._active) if self._active in targets else -1
                target_index = (current + (1 if key == Qt.Key.Key_Down else -1)) % len(
                    targets
                )
                if current < 0:
                    target_index = 0 if key == Qt.Key.Key_Down else len(targets) - 1
                if key == Qt.Key.Key_Home:
                    target_index = 0
                elif key == Qt.Key.Key_End:
                    target_index = len(targets) - 1
                self._highlight(targets[target_index])
            return True
        target = self._active
        if target is None:
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if isinstance(target.widget, QToolButton):
                action = target.widget.defaultAction()
                if action.isEnabled() and action.isVisible():
                    action.trigger()
            elif self._view is not None and target.index.isValid():
                self._view.activated.emit(target.model_index())
            return True
        view = self._view
        if (
            view is not None
            and key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            and target.widget is view
        ):
            index = target.model_index()
            if key == Qt.Key.Key_Right and view.model().hasChildren(index):
                if view.isExpanded(index):
                    self._highlight(
                        _Target(
                            view, QPersistentModelIndex(view.model().index(0, 0, index))
                        )
                    )
                else:
                    view.expand(index)
                return True
            if key == Qt.Key.Key_Left:
                if view.isExpanded(index):
                    view.collapse(index)
                    return True
                if index.parent().isValid():
                    self._highlight(
                        _Target(view, QPersistentModelIndex(index.parent()))
                    )
                    return True
        if key == Qt.Key.Key_Right and isinstance(target.widget, QToolButton):
            action = target.widget.defaultAction()
            if isinstance(action.menu(), QMenu):
                action.trigger()
                return True
        return False

    def hideEvent(self, event: QHideEvent) -> None:
        self._highlight(None, focus=False)
        self.dismissed.emit()
        super().hideEvent(event)


class HoverDropdownGroup(QObject):
    """Own all trigger, popup and nested-menu transitions for a navigation strip."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._popups: list[HoverDropdown] = []
        self._active: HoverDropdown | None = None
        self._blocked: QPushButton | None = None
        self._mode = DropdownOpenMode.HOVER
        self._pressed: QPushButton | None = None
        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.timeout.connect(self._dismiss_outside)

    def add(self, popup: HoverDropdown) -> None:
        self._popups.append(popup)
        trigger = popup.trigger
        trigger.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        trigger.setCheckable(False)
        trigger.setProperty("dropdownTrigger", True)
        self.retranslate_ui()
        trigger.installEventFilter(self)
        trigger.clicked.connect(lambda: self.open(popup, DropdownOpenMode.KEYBOARD))
        popup.dismissed.connect(lambda: self._hidden(popup))

    def retranslate_ui(self) -> None:
        description = self.tr(
            "Opens a menu. Use arrow keys to move, Enter to activate, and Escape to close."
        )
        for popup in self._popups:
            popup.trigger.setAccessibleDescription(description)

    def _at(self, position: QPoint) -> HoverDropdown | None:
        return next(
            (
                p
                for p in self._popups
                if p.trigger.isVisible()
                and p.trigger.isEnabled()
                and p.trigger.rect().contains(p.trigger.mapFromGlobal(position))
            ),
            None,
        )

    def _sync_states(self, position: QPoint) -> None:
        hovered = self._at(position)
        for popup in self._popups:
            trigger = popup.trigger
            trigger.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, popup is hovered)
            _property(trigger, "dropdownHovered", popup is hovered)
            _property(trigger, "dropdownOpen", popup is self._active)
            trigger.update()

    def open(
        self,
        popup: HoverDropdown,
        mode: DropdownOpenMode = DropdownOpenMode.HOVER,
        *,
        last: bool = False,
    ) -> None:
        if not popup.trigger.isVisible() or not popup.trigger.isEnabled():
            return
        if mode is DropdownOpenMode.HOVER and (
            QApplication.mouseButtons() or popup.trigger is self._blocked
        ):
            return
        self._dismiss.stop()
        if self._active is popup:
            if mode is DropdownOpenMode.KEYBOARD:
                self._mode = mode
                popup.highlight_first(last=last)
            return
        self.close()
        self._active = popup
        self._blocked = None
        self._mode = mode
        dragging = mode is DropdownOpenMode.DRAG
        popup.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            if dragging
            else Qt.WindowType.Popup
        )
        popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, dragging)
        popup.aboutToShow.emit()
        popup.fit()
        if not dragging:
            popup.setFocus(Qt.FocusReason.PopupFocusReason)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        popup.show()
        if mode is DropdownOpenMode.KEYBOARD:
            popup.highlight_first(last=last)
        self._sync_states(QCursor.pos())

    def close(self, *, restore_focus: bool = False) -> None:
        popup = self._active
        if popup is None:
            return
        for menu in popup.findChildren(QMenu):
            menu.hide()
        popup.hide()
        if restore_focus and popup.trigger.isVisible() and popup.trigger.isEnabled():
            popup.trigger.setFocus(Qt.FocusReason.PopupFocusReason)

    def _hidden(self, popup: HoverDropdown) -> None:
        if self._active is not popup:
            return
        self._active = None
        self._dismiss.stop()
        if self._pressed is not None:
            self._pressed.setDown(False)
            self._pressed = None
        hovered = self._at(QCursor.pos())
        self._blocked = hovered.trigger if hovered is not None else None
        self._sync_states(QCursor.pos())
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

    def _inside(self, position: QPoint) -> bool:
        popup = self._active
        if popup is None:
            return False
        return (
            popup.rect().contains(popup.mapFromGlobal(position))
            or popup.trigger.rect().contains(popup.trigger.mapFromGlobal(position))
            or any(
                m.isVisible() and m.rect().contains(m.mapFromGlobal(position))
                for m in popup.findChildren(QMenu)
            )
        )

    def _dismiss_outside(self) -> None:
        if self._mode is not DropdownOpenMode.KEYBOARD and not self._inside(
            QCursor.pos()
        ):
            self.close()

    def _switch(self, direction: int) -> None:
        available = [
            p for p in self._popups if p.trigger.isVisible() and p.trigger.isEnabled()
        ]
        if self._active in available:
            self.open(
                available[(available.index(self._active) + direction) % len(available)],
                DropdownOpenMode.KEYBOARD,
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        trigger_popup = next((p for p in self._popups if watched is p.trigger), None)
        popup = self._active
        if (
            popup is not None
            and kind == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.windowType() == Qt.WindowType.Popup
            and watched is not popup
            and watched not in popup.findChildren(QMenu)
        ):
            # Another popup takes over input; only our own submenus share this one.
            self.close()
            return super().eventFilter(watched, event)
        if trigger_popup is not None:
            if kind == QEvent.Type.Enter:
                if popup is None or self._mode is not DropdownOpenMode.DRAG:
                    current = QApplication.activePopupWidget()
                    if current is None or popup is not None:
                        self.open(trigger_popup)
            elif kind == QEvent.Type.Leave:
                self._blocked = None
                self._sync_states(QCursor.pos())
                if popup is not None and self._mode is DropdownOpenMode.HOVER:
                    self._dismiss.start(180)
            elif (
                kind in (QEvent.Type.Hide, QEvent.Type.EnabledChange)
                and popup is trigger_popup
            ):
                self.close()
        if isinstance(event, QMouseEvent):
            position = event.globalPosition().toPoint()
            hovered = self._at(position)
            if (
                kind == QEvent.Type.MouseButtonRelease
                and self._pressed is not None
                and (hovered is None or hovered.trigger is not self._pressed)
            ):
                self._pressed.setDown(False)
                self._pressed = None
            if hovered is not None and kind in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            ):
                if event.button() == Qt.MouseButton.LeftButton:
                    if kind == QEvent.Type.MouseButtonPress:
                        self._pressed = hovered.trigger
                        hovered.trigger.setDown(True)
                    elif kind == QEvent.Type.MouseButtonRelease:
                        pressed = self._pressed
                        self._pressed = None
                        hovered.trigger.setDown(False)
                        if pressed is hovered.trigger:
                            self.open(hovered, DropdownOpenMode.KEYBOARD)
                event.accept()
                return True
            if (
                popup is not None
                and kind == QEvent.Type.MouseMove
                and not event.buttons()
                and self._mode is not DropdownOpenMode.DRAG
            ):
                self._mode = DropdownOpenMode.HOVER
                self._sync_states(position)
                if hovered is None or hovered.trigger is not self._blocked:
                    self._blocked = None
                if hovered is not None:
                    self.open(hovered)
                    return True
                if self._inside(position):
                    self._dismiss.stop()
                    popup.point_at(position)
                elif not self._dismiss.isActive():
                    self._dismiss.start(180)
            elif (
                popup is not None
                and kind == QEvent.Type.MouseButtonPress
                and not self._inside(position)
            ):
                self.close()
        if isinstance(event, QKeyEvent) and kind == QEvent.Type.KeyPress:
            nested = QApplication.activePopupWidget()
            if (
                popup is not None
                and nested is not None
                and nested is not popup
                and nested in popup.findChildren(QMenu)
            ):
                return False
            if (
                popup is not None
                and trigger_popup is None
                and (not isinstance(watched, QWidget) or watched.window() is not popup)
            ):
                return False
            key = event.key()
            if trigger_popup is not None and key in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
                Qt.Key.Key_Down,
                Qt.Key.Key_Up,
                Qt.Key.Key_Menu,
                Qt.Key.Key_F10,
            ):
                self.open(
                    trigger_popup, DropdownOpenMode.KEYBOARD, last=key == Qt.Key.Key_Up
                )
                return True
            if popup is not None:
                self._mode = DropdownOpenMode.KEYBOARD
                self._dismiss.stop()
                if key == Qt.Key.Key_Escape:
                    self.close(restore_focus=True)
                    return True
                if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                    trigger = popup.trigger
                    self.close(restore_focus=True)
                    QApplication.sendEvent(
                        trigger, QKeyEvent(QEvent.Type.KeyPress, key, event.modifiers())
                    )
                    return True
                if popup.navigate(key):
                    return True
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    self._switch(-1 if key == Qt.Key.Key_Left else 1)
                    return True
        if popup is not None:
            if kind == QEvent.Type.ApplicationDeactivate or (
                watched is popup.trigger.window()
                and kind in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide)
            ):
                self.close()
            elif kind == QEvent.Type.Leave and self._mode is DropdownOpenMode.HOVER:
                self._dismiss.start(180)
            elif self._mode is DropdownOpenMode.DRAG:
                if kind in (QEvent.Type.Drop, QEvent.Type.MouseButtonRelease):
                    QTimer.singleShot(0, popup, popup.hide)
                elif isinstance(event, QDragMoveEvent) and isinstance(watched, QWidget):
                    position = watched.mapToGlobal(event.position().toPoint())
                    if self._inside(position):
                        self._dismiss.stop()
                    elif not self._dismiss.isActive():
                        self._dismiss.start(500)
        return super().eventFilter(watched, event)
