"""Sync membership, stream chooser, and saved-choice status in one compact cell."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    Qt,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.sync_media import sync_checkbox_tokens
from iOpenPod.GUI.presentation.theme.checkbox_style import CheckboxStyle
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class SyncTrackDelegate(QStyledItemDelegate):
    """Paint iPod presence, selection, and stream controls without row widgets."""

    def __init__(self, theme_manager: ThemeManager, parent: QWidget) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self.hovered_button = QPersistentModelIndex()
        self.pressed_button = QPersistentModelIndex()

    @staticmethod
    def ipod_rect(cell: QRect) -> QRect:
        return QRect(cell.left() + 4, cell.center().y() - 10, 20, 20)

    @staticmethod
    def checkbox_rect(cell: QRect) -> QRect:
        extent = LAYOUT.checkbox_indicator_size
        return QRect(cell.left() + 28, cell.center().y() - extent // 2, extent, extent)

    @staticmethod
    def button_rect(cell: QRect) -> QRect:
        return QRect(cell.left() + 60, cell.center().y() - 14, 28, 28)

    def minimum_width(self) -> int:
        parent = self.parent()
        assert isinstance(parent, QWidget)
        labels = (self.tr("Auto"), self.tr("Manual"))
        return 108 + max(
            parent.fontMetrics().horizontalAdvance(text) for text in labels
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        manual = index.data(TrackRole.STREAM_MANUAL)
        if manual is None:
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        style = option.widget.style()
        checkbox = QStyleOptionButton()
        checkbox.rect = self.checkbox_rect(option.rect)
        checkbox.state = option.state & ~(
            QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off
        )
        checkbox.state |= (
            QStyle.StateFlag.State_On
            if styled.checkState == Qt.CheckState.Checked
            else QStyle.StateFlag.State_Off
        )
        styled.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, styled, painter, option.widget
        )
        tokens = self._theme_manager.tokens
        on_ipod = index.data(TrackRole.ON_IPOD) is True
        CheckboxStyle.paint_indicator(
            painter, checkbox, sync_checkbox_tokens(tokens, styled.checkState, on_ipod)
        )
        if on_ipod:
            glyph_icon(
                "ipod", 20, QColor(tokens.text), option.widget.devicePixelRatioF()
            ).paint(painter, self.ipod_rect(option.rect))
        button = self.button_rect(option.rect)
        badge = QRect(
            button.right() + 6,
            option.rect.center().y() - 10,
            max(0, option.rect.right() - button.right() - 12),
            20,
        )
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.hovered_button == index
        pressed = hovered and self.pressed_button == index
        painter.setPen(QColor(tokens.accent if hovered else tokens.border_strong))
        painter.setBrush(
            QColor(
                tokens.surface_pressed
                if pressed
                else tokens.surface_hover
                if hovered
                else tokens.surface
            )
        )
        painter.drawRoundedRect(button, 5, 5)
        glyph_icon(
            "choose-streams",
            18,
            QColor(tokens.text),
            option.widget.devicePixelRatioF(),
        ).paint(painter, button.adjusted(5, 5, -5, -5))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.accent if manual else tokens.surface_alt))
        painter.drawRoundedRect(badge, 10, 10)
        painter.setPen(QColor(tokens.accent_ink if manual else tokens.text_secondary))
        painter.drawText(
            badge,
            Qt.AlignmentFlag.AlignCenter,
            self.tr("Manual") if manual else self.tr("Auto"),
        )
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not (
            index.flags() & Qt.ItemFlag.ItemIsUserCheckable
            and index.flags() & Qt.ItemFlag.ItemIsEnabled
            and option.state & QStyle.StateFlag.State_Enabled
        ):
            return False
        if isinstance(event, QMouseEvent):
            if (
                event.button() is not Qt.MouseButton.LeftButton
                or not self.checkbox_rect(option.rect).contains(
                    event.position().toPoint()
                )
            ):
                return False
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            ):
                return True
            if event.type() is not QEvent.Type.MouseButtonRelease:
                return False
        elif isinstance(event, QKeyEvent):
            if event.type() is not QEvent.Type.KeyPress or event.key() not in (
                Qt.Key.Key_Space,
                Qt.Key.Key_Select,
            ):
                return False
        else:
            return False
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        return model.setData(
            index,
            Qt.CheckState.Unchecked
            if state == Qt.CheckState.Checked
            else Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
