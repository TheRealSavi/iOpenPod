"""Render reviewed rating changes with themed stars in Sync item views."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.app.models.sync_plan_table_model import SyncPlanRole
from iOpenPod.app.sync_plan import SyncPlanItem
from iOpenPod.GUI.presentation.theme.tokens import tokens_for

if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex, QPersistentModelIndex
    from PySide6.QtGui import QPainter

    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class RatingReasonDelegate(QStyledItemDelegate):
    """Paint the rating glyphs with the same theme color as the Player."""

    def __init__(self, view: QTableView, theme_manager: ThemeManager | None) -> None:
        super().__init__(view)
        self._theme_manager = theme_manager

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        item = index.data(SyncPlanRole.ITEM)
        if not isinstance(item, SyncPlanItem) or item.rating is None:
            super().paint(painter, option, index)
            return

        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        style = styled.widget.style() if styled.widget else QApplication.style()
        rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, styled, styled.widget
        )
        text = styled.fontMetrics.elidedText(
            styled.text, styled.textElideMode, rect.width()
        )
        styled.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget
        )

        tokens = (
            self._theme_manager.tokens
            if self._theme_manager is not None
            else tokens_for(
                DarkTheme.SLATE
                if styled.palette.color(QPalette.ColorRole.Base).lightnessF() < 0.5
                else LightTheme.PORCELAIN
            )
        )
        star_format = QTextCharFormat()
        star_format.setForeground(QColor(tokens.warning))
        formats: list[QTextLayout.FormatRange] = []
        for match in re.finditer(r"[★☆]+", text):
            span = QTextLayout.FormatRange()
            # Qt counts UTF-16 units, which matters for localized text with emoji.
            span.start = len(text[: match.start()].encode("utf-16-le")) // 2
            span.length = len(match.group())
            span.format = star_format
            formats.append(span)
        layout = QTextLayout(text, styled.font)
        layout.setFormats(formats)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(rect.width())
        layout.endLayout()

        painter.save()
        painter.setClipRect(rect)
        role = (
            QPalette.ColorRole.HighlightedText
            if styled.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.setPen(styled.palette.color(role))
        layout.draw(
            painter,
            QPointF(rect.left(), rect.top() + (rect.height() - line.height()) / 2),
        )
        painter.restore()
