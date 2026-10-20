"""Structured stream rows using the application's palette and native checks.

Hallmark · component: stream option · theme: inherited iOpenPod
States: idle, hover, focus, checked, disabled; loading/errors remain dialog-owned.
Pre-emit critique: P5 H5 E5 S5 R5 V4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QFont, QPainter, QPalette, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QFrame, QStyle, QStyleOptionViewItem

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.checkable_combo_box import (
    SUMMARY_ROLE,
    CheckableComboBox,
    SelectionDelegate,
)

STREAM_OPTION_ROLE = SUMMARY_ROLE + 1
_PADDING = LAYOUT.space_sm
_GAP = LAYOUT.space_2xs


@dataclass(frozen=True, slots=True)
class StreamOption:
    title: str
    details: str
    status: str
    number: str
    summary: str

    @property
    def accessible_text(self) -> str:
        return "\n".join(
            part
            for part in (self.title, self.number, self.details, self.status)
            if part
        )


def set_stream_option(combo: AppComboBox, index: int, option: StreamOption) -> None:
    combo.setItemData(index, option, STREAM_OPTION_ROLE)
    combo.setItemData(index, option.summary, SUMMARY_ROLE)
    combo.setItemData(index, option.accessible_text, Qt.ItemDataRole.AccessibleTextRole)
    # The popup already displays the information; don't cover it with a tooltip.
    combo.setItemData(index, None, Qt.ItemDataRole.ToolTipRole)
    if isinstance(combo, CheckableComboBox):
        combo.refresh_summary()


def _layout(text: str, font: QFont, width: int) -> QTextLayout:
    layout = QTextLayout(text, font)
    options = QTextOption()
    options.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(options)
    layout.beginLayout()
    height = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1, width))
        line.setPosition(QPointF(0, height))
        height += line.height()
    layout.endLayout()
    return layout


class StreamOptionDelegate(SelectionDelegate):
    """Paint complete rectangular options without allocating widgets per row."""

    def __init__(self, combo: AppComboBox) -> None:
        super().__init__(combo)
        self._combo = combo
        combo.setItemDelegate(self)
        combo.setLabelDrawingMode(combo.LabelDrawingMode.UseDelegate)
        combo.setSizeAdjustPolicy(
            combo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumContentsLength(12)
        combo.setMaxVisibleItems(5)
        combo.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        combo.view().setMouseTracking(True)
        self._popup = combo.view().window()
        self._popup.installEventFilter(self)
        combo.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() in (QEvent.Type.Resize, QEvent.Type.Show)
            and watched is self._combo
        ) or (event.type() == QEvent.Type.Show and watched is self._popup):
            border = self._popup.frameWidth() if isinstance(self._popup, QFrame) else 0
            self._popup.setFixedWidth(self._combo.width())
            self._combo.view().setFixedWidth(max(1, self._combo.width() - 2 * border))
        return super().eventFilter(watched, event)

    def _blocks(
        self, option: QStyleOptionViewItem, data: StreamOption, width: int
    ) -> tuple[QTextLayout, ...]:
        font = QFont(option.font)
        font.setBold(True)
        return (
            _layout(data.title, font, width),
            _layout(data.details, option.font, width),
            *((_layout(data.status, option.font, width),) if data.status else ()),
        )

    def _text_width(self, width: int) -> int:
        return max(
            1,
            width
            - 2 * (_PADDING + _GAP)
            - (
                LAYOUT.checkbox_indicator_size + LAYOUT.space_xs
                if isinstance(self._combo, CheckableComboBox)
                else 0
            ),
        )

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        data = index.data(STREAM_OPTION_ROLE)
        if isinstance(option.widget, AppComboBox):
            return QSize(180, option.fontMetrics.height())
        if not isinstance(data, StreamOption):
            return super().sizeHint(option, index)
        width = max(1, self._combo.view().viewport().width())
        blocks = self._blocks(option, data, self._text_width(width))
        height = (
            2 * (_PADDING + _GAP)
            + option.fontMetrics.height()
            + _GAP
            + sum(math.ceil(block.boundingRect().height()) + _GAP for block in blocks)
        )
        return QSize(width, height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        data = index.data(STREAM_OPTION_ROLE)
        if isinstance(option.widget, CheckableComboBox) or not isinstance(
            data, StreamOption
        ):
            super().paint(painter, option, index)
            return
        if isinstance(option.widget, AppComboBox):
            painter.save()
            painter.setPen(
                option.palette.color(
                    QPalette.ColorGroup.Active
                    if option.widget.isEnabled()
                    else QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.ButtonText,
                )
            )
            painter.drawText(
                option.rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading,
                option.fontMetrics.elidedText(
                    data.summary, Qt.TextElideMode.ElideRight, option.rect.width()
                ),
            )
            painter.restore()
            return
        self._paint_option(painter, option, index, data)

    def _paint_option(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        data: StreamOption,
    ) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
        highlighted = enabled and bool(
            styled.state
            & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        )
        # Widget QSS derives translucent placeholders and can override disabled
        # item colors. The application palette retains the theme's semantic colors.
        palette = QApplication.palette()
        rect = styled.rect.adjusted(_GAP, _GAP, -_GAP, -_GAP)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                palette.color(
                    group,
                    QPalette.ColorRole.Accent
                    if highlighted
                    else QPalette.ColorRole.Mid,
                )
            )
        )
        painter.setBrush(
            palette.brush(
                group,
                QPalette.ColorRole.AlternateBase
                if highlighted
                else QPalette.ColorRole.Base,
            )
        )
        painter.drawRoundedRect(
            QRectF(rect), LAYOUT.radius_control, LAYOUT.radius_control
        )
        x, y = rect.left() + _PADDING, rect.top() + _PADDING
        if isinstance(self._combo, CheckableComboBox):
            check = QStyleOptionViewItem(styled)
            check.palette = palette
            if not enabled:
                check.state &= ~(
                    QStyle.StateFlag.State_Enabled
                    | QStyle.StateFlag.State_HasFocus
                    | QStyle.StateFlag.State_MouseOver
                )
            check.rect = QRect(
                x, y, LAYOUT.checkbox_indicator_size, LAYOUT.checkbox_indicator_size
            )
            check.state &= ~(QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off)
            check.state |= (
                QStyle.StateFlag.State_On
                if styled.checkState == Qt.CheckState.Checked
                else QStyle.StateFlag.State_Off
            )
            self._combo.style().drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
                check,
                painter,
                self._combo,
            )
            x += LAYOUT.checkbox_indicator_size + LAYOUT.space_xs
        width = self._text_width(styled.rect.width())
        painter.setFont(styled.font)
        painter.setPen(palette.color(group, QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            QRect(x, y, width, styled.fontMetrics.height()),
            Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter,
            data.number,
        )
        y += styled.fontMetrics.height() + _GAP
        for position, block in enumerate(self._blocks(styled, data, width)):
            painter.setPen(
                palette.color(
                    group,
                    QPalette.ColorRole.Text
                    if position == 0
                    else QPalette.ColorRole.PlaceholderText,
                )
            )
            block.draw(painter, QPointF(x, y))
            y += math.ceil(block.boundingRect().height()) + _GAP
        painter.restore()
