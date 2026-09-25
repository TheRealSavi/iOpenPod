# Hallmark · component: collapsible selection-group header · genre: modern-minimal
# theme: iOpenPod · states: expanded · collapsed · hover · focus · pressed · disabled
# contrast: pass (40-41) · pre-emit critique: P5 H5 E5 S5 R5 V4
"""Delegate wrapper that adds full-width collapsible selection headers."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QStyleOption,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.app.models.selection_grouping import SelectionGroupingRole
from iOpenPod.GUI.presentation.selection_checkbox import library_card_checkbox_rect
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView
from iOpenPod.GUI.widgets.selection_group_transition import SelectionGroupTransition


class SelectionGroupDelegate(QStyledItemDelegate):
    """Paint section rows and delegate ordinary rows to the existing renderer."""

    def __init__(
        self,
        item_delegate: QAbstractItemDelegate,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_delegate = item_delegate
        self._theme_manager = theme_manager
        self._view = parent if isinstance(parent, QAbstractItemView) else None
        self._viewport = self._view.viewport() if self._view is not None else None
        self._pressed_header = QPersistentModelIndex()
        self._pressed_checkbox = QPersistentModelIndex()
        self._control_press_active = False
        self._transition = (
            SelectionGroupTransition(self._view)
            if isinstance(self._view, EqualizedGridView)
            else None
        )
        if self._view is not None and self._viewport is not None:
            self._view.installEventFilter(self)
            self._viewport.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        view = self._view
        if view is None or (watched is not view and watched is not self._viewport):
            return super().eventFilter(watched, event)
        if isinstance(event, QMouseEvent):
            if watched is not self._viewport:
                return False
            index = view.indexAt(event.position().toPoint())
            is_header = bool(index.data(SelectionGroupingRole.IS_HEADER))
            if (
                event.type() is QEvent.Type.MouseButtonPress
                and event.button() is Qt.MouseButton.LeftButton
            ):
                self._pressed_header = (
                    QPersistentModelIndex(index)
                    if is_header
                    else QPersistentModelIndex()
                )
                checkbox_hit = not is_header and self._checkbox_hit(
                    index, event.position().toPoint()
                )
                self._pressed_checkbox = (
                    QPersistentModelIndex(index)
                    if checkbox_hit
                    else QPersistentModelIndex()
                )
                self._control_press_active = is_header or checkbox_hit
                if self._control_press_active:
                    view.setFocus(Qt.FocusReason.MouseFocusReason)
                    return True
            elif event.type() is QEvent.Type.MouseMove and self._control_press_active:
                # The view never saw this press, so it must not receive a drag
                # using a stale selection anchor, even if the index was removed.
                return True
            elif (
                event.type() is QEvent.Type.MouseButtonRelease
                and event.button() is Qt.MouseButton.LeftButton
            ):
                control_press_active = self._control_press_active
                self._control_press_active = False
                pressed = self._pressed_header
                self._pressed_header = QPersistentModelIndex()
                pressed_checkbox = self._pressed_checkbox
                self._pressed_checkbox = QPersistentModelIndex()
                if not control_press_active:
                    # A box selection started in the view must finish there,
                    # including when its release lands on a control.
                    return False
                if pressed.isValid() and is_header and pressed == index:
                    self._toggle(index)
                elif pressed_checkbox.isValid() and pressed_checkbox == index:
                    self._item_delegate.editorEvent(
                        event,
                        view.model(),
                        self._view_item_option(view, index),
                        index,
                    )
                return True
        elif isinstance(event, QKeyEvent) and watched is view:
            if event.type() is QEvent.Type.KeyPress and event.key() in {
                Qt.Key.Key_Enter,
                Qt.Key.Key_Return,
                Qt.Key.Key_Select,
                Qt.Key.Key_Space,
            }:
                index = view.currentIndex()
                if bool(index.data(SelectionGroupingRole.IS_HEADER)):
                    return self._toggle(index)
        # Qt's delegate filter treats its target as an editor. The view and
        # viewport are navigation surfaces, so their focus/key/hide events must
        # continue normally without emitting commitData or closeEditor for them.
        return False

    def _checkbox_hit(self, index: QModelIndex, point: QPoint) -> bool:
        view = self._view
        if (
            view is None
            or not isinstance(view, EqualizedGridView)
            or not index.flags() & Qt.ItemFlag.ItemIsUserCheckable
        ):
            return False
        option = self._view_item_option(view, index)
        return library_card_checkbox_rect(
            option,
            self._theme_manager.typography,
        ).contains(point)

    @staticmethod
    def _view_item_option(
        view: QAbstractItemView,
        index: QModelIndex,
    ) -> QStyleOptionViewItem:
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.font = view.font()
        option.rect = view.visualRect(index)
        return option

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        widget = option.widget
        if bool(index.data(SelectionGroupingRole.IS_HEADER)):
            width = (
                widget.section_header_width()
                if isinstance(widget, EqualizedGridView)
                else widget.viewport().width()
                if isinstance(widget, QAbstractItemView)
                else option.rect.width()
            )
            return QSize(max(1, width), LAYOUT.control_height_large)
        item_size = self._item_delegate.sizeHint(option, index)
        if isinstance(widget, EqualizedGridView) and widget.sectioned_layout:
            return widget.sectioned_item_size(item_size)
        return item_size

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not bool(index.data(SelectionGroupingRole.IS_HEADER)):
            self._item_delegate.paint(painter, option, index)
            return

        tokens = self._theme_manager.tokens
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        expanded = bool(index.data(SelectionGroupingRole.EXPANDED))
        background = (
            tokens.surface_alt
            if not enabled
            else tokens.surface_pressed
            if pressed
            else tokens.surface_hover
            if hovered
            else tokens.surface
        )
        foreground = tokens.text if enabled else tokens.text_disabled

        painter.save()
        painter.fillRect(option.rect, QColor(background))
        border_pen = QPen(QColor(tokens.border))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

        arrow_extent = LAYOUT.icon_size
        arrow_rect = QRect(
            option.rect.left() + LAYOUT.space_sm,
            option.rect.center().y() - arrow_extent // 2,
            arrow_extent,
            arrow_extent,
        )
        arrow_option = QStyleOption()
        arrow_option.initFrom(option.widget)
        arrow_option.rect = arrow_rect
        arrow_option.palette.setColor(
            QPalette.ColorRole.WindowText,
            QColor(foreground),
        )
        primitive = (
            QStyle.PrimitiveElement.PE_IndicatorArrowDown
            if expanded
            else QStyle.PrimitiveElement.PE_IndicatorArrowRight
        )
        option.widget.style().drawPrimitive(
            primitive,
            arrow_option,
            painter,
            option.widget,
        )

        label_rect = option.rect.adjusted(
            LAYOUT.space_sm + arrow_extent + LAYOUT.space_2xs,
            0,
            -LAYOUT.space_sm,
            0,
        )
        label_font = QFont(option.font)
        label_font.setPointSizeF(self._theme_manager.typography.heading_pt)
        label_font.setWeight(QFont.Weight.Bold)
        painter.setFont(label_font)
        painter.setPen(QColor(foreground))
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )

        if focused:
            focus_pen = QPen(QColor(tokens.focus))
            focus_pen.setWidth(2)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                option.rect.adjusted(1, 1, -2, -2),
                LAYOUT.radius_control,
                LAYOUT.radius_control,
            )
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if (
            isinstance(event, QMouseEvent)
            and event.type() is QEvent.Type.MouseButtonRelease
            and self._view is not None
            and self._view.state() is QAbstractItemView.State.DragSelectingState
        ):
            # Qt can offer the drag's release to the delegate when it ends on
            # the pressed card. Finish selection without activating a control.
            return False
        if not bool(index.data(SelectionGroupingRole.IS_HEADER)):
            return self._item_delegate.editorEvent(event, model, option, index)
        if not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return False
        activate = False
        if isinstance(event, QMouseEvent):
            activate = (
                event.type() is QEvent.Type.MouseButtonRelease
                and event.button() is Qt.MouseButton.LeftButton
                and option.rect.contains(event.position().toPoint())
            )
        elif isinstance(event, QKeyEvent):
            activate = event.type() is QEvent.Type.KeyPress and event.key() in {
                Qt.Key.Key_Enter,
                Qt.Key.Key_Return,
                Qt.Key.Key_Select,
                Qt.Key.Key_Space,
            }
        if not activate:
            return False
        return self._toggle(index)

    def _toggle(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        if self._transition is not None:
            return self._transition.toggle(index)
        model = index.model()
        return model.setData(
            index,
            not bool(index.data(SelectionGroupingRole.EXPANDED)),
            SelectionGroupingRole.EXPANDED,
        )


__all__ = ["SelectionGroupDelegate"]
