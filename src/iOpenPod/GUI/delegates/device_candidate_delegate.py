"""Paint a Device Candidate's product artwork, identity and selection."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, TypographyTokens


class DeviceCandidateDelegate(QStyledItemDelegate):
    """Use the list's themed item surface and native keyboard focus."""

    subtitle_role = Qt.ItemDataRole.UserRole.value + 1

    def __init__(self, typography: TypographyTokens, parent: QWidget) -> None:
        super().__init__(parent)
        self._typography = typography

    def _title_font(self, base: QFont) -> QFont:
        font = QFont(base)
        font.setPointSizeF(self._typography.heading_pt)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        text_height = (
            QFontMetrics(self._title_font(option.font)).height()
            + LAYOUT.space_2xs
            + option.fontMetrics.height()
        )
        return QSize(
            0, max(LAYOUT.device_picker_row_height, text_height + 2 * LAYOUT.space_md)
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        surface = QStyleOptionViewItem(option)
        self.initStyleOption(surface, index)
        name, icon = surface.text, QIcon(surface.icon)
        surface.text = ""
        surface.icon = QIcon()
        surface.rect = surface.rect.adjusted(0, LAYOUT.space_3xs, 0, -LAYOUT.space_3xs)
        widget = option.widget
        style = widget.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, surface, painter, widget
        )

        cell = surface.rect.adjusted(LAYOUT.space_md, 0, -LAYOUT.space_md, 0)
        art_size = LAYOUT.device_picker_image_size
        art = QRect(cell.x(), cell.center().y() - art_size // 2, art_size, art_size)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        icon.paint(
            painter,
            art,
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled,
        )

        group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
        palette = QApplication.palette()
        mark_size = LAYOUT.icon_size
        mark = QRect(
            cell.right() - mark_size + 1,
            cell.center().y() - mark_size // 2,
            mark_size,
            mark_size,
        )
        if option.state & QStyle.StateFlag.State_Selected:
            color = palette.color(
                group, QPalette.ColorRole.Accent if enabled else QPalette.ColorRole.Text
            )
            glyph_icon(
                "check", mark_size, color, painter.device().devicePixelRatioF()
            ).paint(painter, mark)

        left = art.right() + 1 + LAYOUT.space_md
        width = max(0, mark.left() - LAYOUT.space_sm - left)
        title_font = self._title_font(option.font)
        title_metrics = QFontMetrics(title_font)
        detail = str(index.data(self.subtitle_role) or "")
        height = title_metrics.height()
        if detail:
            height += LAYOUT.space_2xs + option.fontMetrics.height()
        top = cell.y() + (cell.height() - height) // 2
        painter.save()
        painter.setFont(title_font)
        painter.setPen(palette.color(group, QPalette.ColorRole.Text))
        painter.drawText(
            QRect(left, top, width, title_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(name, Qt.TextElideMode.ElideRight, width),
        )
        if detail:
            painter.setFont(option.font)
            painter.setPen(palette.color(group, QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                QRect(
                    left,
                    top + title_metrics.height() + LAYOUT.space_2xs,
                    width,
                    option.fontMetrics.height(),
                ),
                Qt.AlignmentFlag.AlignVCenter,
                option.fontMetrics.elidedText(
                    detail, Qt.TextElideMode.ElideRight, width
                ),
            )
        painter.restore()
