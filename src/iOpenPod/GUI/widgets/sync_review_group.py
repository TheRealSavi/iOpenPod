# Hallmark · component: Sync Review group · theme: iOpenPod
# pre-emit critique: P5 H5 E4 S5 R5 V4
"""Collapsible change groups with bounded, virtualized detail tables."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextLayout
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.app.models.sync_plan_table_model import (
    SyncPlanColumn,
    SyncPlanFilterModel,
    SyncPlanRole,
)
from iOpenPod.app.sync_plan import SyncPlanAction, SyncPlanItem, SyncPlanMediaKind
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, tokens_for
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex, QPersistentModelIndex
    from PySide6.QtGui import QPainter

    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class _RatingReasonDelegate(QStyledItemDelegate):
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


class _GroupCheckBox(QCheckBox):
    """Display mixed state, but make activation select or deselect the group."""

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked
            if self.checkState() is Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )


class _ActionSymbol(QLabel):
    """Render packaged glyphs with the semantic color supplied by the theme."""

    def __init__(self, action: SyncPlanAction, parent: QWidget) -> None:
        self._glyph = {
            SyncPlanAction.ADD: "plus",
            SyncPlanAction.REMOVE: "minus",
            SyncPlanAction.UPDATE: "refresh",
            SyncPlanAction.ATTENTION: "alert",
            SyncPlanAction.UNCHANGED: "check-circle",
        }[action]
        super().__init__(parent)
        self.setObjectName("syncReviewSymbol")
        self.setProperty("action", action.value)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(LAYOUT.icon_button_size, LAYOUT.icon_button_size)
        self._refresh_icon()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.StyleChange}:
            self._refresh_icon()
        super().changeEvent(event)

    def _refresh_icon(self) -> None:
        self.setPixmap(
            glyph_icon(
                self._glyph,
                LAYOUT.icon_size,
                self.palette().color(QPalette.ColorRole.WindowText),
                self.devicePixelRatioF(),
            ).pixmap(
                QSize(LAYOUT.icon_size, LAYOUT.icon_size), self.devicePixelRatioF()
            )
        )


class SyncReviewGroup(QFrame):
    """Keep group controls constant in number, irrespective of Library size."""

    checkedRequested = Signal(bool)

    def __init__(
        self,
        source: SyncPlanFilterModel,
        action: SyncPlanAction,
        media: SyncPlanMediaKind | None,
        parent: QWidget | None = None,
        *,
        header_action: QWidget | None = None,
        replaces_payload: bool | None = None,
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncReviewGroup")
        self.setProperty("action", action.value)
        self.setProperty("media", media.value if media is not None else "all")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action = action
        self.media = media
        self._header_action = header_action
        self._replaces_payload = replaces_payload
        self.proxy = SyncPlanFilterModel(self, replaces_payload=replaces_payload)
        self.proxy.setSourceModel(source)
        self.proxy.set_actions(frozenset({action}))
        self.proxy.set_media_kind(media)

        self.checkbox = _GroupCheckBox(self)
        self.checkbox.setObjectName("syncReviewGroupCheck")
        self.checkbox.setTristate(True)
        self.checkbox.setMinimumSize(
            LAYOUT.control_height_large, LAYOUT.control_height_large
        )
        self.checkbox.clicked.connect(
            lambda: self.checkedRequested.emit(
                self.checkbox.checkState() is Qt.CheckState.Checked
            )
        )

        self.toggle = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self.toggle.setObjectName("syncReviewGroupToggle")
        self.toggle.setCheckable(True)
        self.toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._symbol = _ActionSymbol(action, self.toggle)
        self._title = QLabel(self.toggle)
        self._title.setObjectName("syncReviewGroupTitle")
        self._subtitle = QLabel(self.toggle)
        self._subtitle.setObjectName("syncReviewGroupSubtitle")
        self._subtitle.setWordWrap(True)
        self._selected = QLabel(self.toggle)
        self._selected.setObjectName("syncReviewGroupSelected")
        self._count = QLabel(self.toggle)
        self._count.setObjectName("syncReviewGroupCount")
        self._count.setProperty("action", action.value)
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chevron = QToolButton(self.toggle)
        self._chevron.setObjectName("syncReviewChevron")
        self._chevron.setAutoRaise(True)
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for label in self.toggle.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(LAYOUT.space_3xs)
        title_layout.addWidget(self._title)
        title_layout.addWidget(self._subtitle)
        toggle_layout = QHBoxLayout(self.toggle)
        toggle_layout.setContentsMargins(
            LAYOUT.space_xs, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm
        )
        toggle_layout.setSpacing(LAYOUT.space_sm)
        toggle_layout.addWidget(self._symbol)
        toggle_layout.addLayout(title_layout, 1)
        toggle_layout.addWidget(self._selected)
        if header_action is not None:
            toggle_layout.addWidget(header_action)
        toggle_layout.addWidget(self._count)
        toggle_layout.addWidget(self._chevron)
        header = QHBoxLayout()
        header.setContentsMargins(LAYOUT.space_xs, 0, 0, 0)
        header.setSpacing(0)
        header.addWidget(self.checkbox)
        header.addWidget(self.toggle, 1)

        self.table = QTableView(self)
        self.table.setObjectName("syncPlanTable")
        self.table.setModel(self.proxy)
        if action is SyncPlanAction.UPDATE and media is SyncPlanMediaKind.TRACK:
            self.table.setItemDelegateForColumn(
                SyncPlanColumn.REASON, _RatingReasonDelegate(self.table, theme_manager)
            )
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(SyncPlanColumn.NAME, Qt.SortOrder.AscendingOrder)
        self.table.setColumnHidden(SyncPlanColumn.MEDIA, media is not None)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(LAYOUT.track_row_height)
        columns = self.table.horizontalHeader()
        columns.setMinimumSectionSize(LAYOUT.control_height_large)
        columns.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        columns.setSectionResizeMode(
            SyncPlanColumn.NAME, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(SyncPlanColumn.ACTION, 112)
        self.table.setColumnWidth(SyncPlanColumn.MEDIA, 84)
        self.table.setColumnWidth(SyncPlanColumn.HOST, 180)
        self.table.setColumnWidth(SyncPlanColumn.IPOD, 180)
        self.table.setColumnWidth(
            SyncPlanColumn.REASON, 290 if media is SyncPlanMediaKind.TRACK else 220
        )
        self.table.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.table)
        self.toggle.toggled.connect(self.set_expanded)
        self.retranslate_ui()

    def items(self) -> tuple[SyncPlanItem, ...]:
        return tuple(
            item
            for row in range(self.proxy.rowCount())
            if isinstance(
                item := self.proxy.index(row, 0).data(SyncPlanRole.ITEM), SyncPlanItem
            )
        )

    def refresh(self) -> None:
        count = self.proxy.rowCount()
        self.setVisible(
            count > 0
            or (self._header_action is not None and not self._header_action.isHidden())
        )
        self.toggle.setCheckable(count > 0)
        self._chevron.setVisible(count > 0)
        if not count:
            self.set_expanded(False)
        states = tuple(
            self.proxy.index(row, SyncPlanColumn.ACTION).data(
                Qt.ItemDataRole.CheckStateRole
            )
            for row in range(count)
        )
        actionable = sum(state is not None for state in states)
        selected = sum(state is Qt.CheckState.Checked for state in states)
        self.checkbox.setVisible(actionable > 0)
        self.checkbox.setCheckState(
            Qt.CheckState.Unchecked
            if selected == 0
            else Qt.CheckState.Checked
            if selected == actionable
            else Qt.CheckState.PartiallyChecked
        )
        self._selected.setText(
            self.tr("%1 of %2 selected")
            .replace("%1", f"{selected:,}")
            .replace("%2", f"{actionable:,}")
            if actionable
            else ""
        )
        self._count.setText(f"{count:,}")
        self.table.setFixedHeight(
            min(count, LAYOUT.sync_review_visible_rows) * LAYOUT.track_row_height
            + self.table.horizontalHeader().sizeHint().height()
            + LAYOUT.scrollbar_extent
            + LAYOUT.space_2xs
        )
        self.toggle.setAccessibleName(
            f"{self._title.text()}, {count:,}. {self._selected.text()}"
        )

    def set_expanded(self, expanded: bool) -> None:
        expanded = expanded and self.proxy.rowCount() > 0
        self.toggle.setChecked(expanded)
        self.table.setVisible(expanded)
        self._chevron.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.toggle.setToolTip(
            self.tr("Collapse group") if expanded else self.tr("Expand group")
        )

    def retranslate_ui(self) -> None:
        titles: dict[tuple[SyncPlanAction, SyncPlanMediaKind | None], str] = {
            (SyncPlanAction.ADD, SyncPlanMediaKind.TRACK): self.tr("Add Items"),
            (SyncPlanAction.REMOVE, SyncPlanMediaKind.TRACK): self.tr("Remove Items"),
            (SyncPlanAction.UPDATE, SyncPlanMediaKind.TRACK): self.tr("Re-sync Files"),
            (SyncPlanAction.ADD, SyncPlanMediaKind.PHOTO): self.tr("Add Photos"),
            (SyncPlanAction.REMOVE, SyncPlanMediaKind.PHOTO): self.tr("Remove Photos"),
            (SyncPlanAction.UPDATE, SyncPlanMediaKind.PHOTO): self.tr("Re-sync Photos"),
            (SyncPlanAction.ATTENTION, None): self.tr("Needs Attention"),
            (SyncPlanAction.UNCHANGED, None): self.tr("Already in Sync"),
        }
        descriptions = {
            SyncPlanAction.ADD: self.tr("Copy selected media to the iPod"),
            SyncPlanAction.REMOVE: self.tr("Remove selected media from the iPod"),
            SyncPlanAction.UPDATE: self.tr(
                "Replace iPod files with changed Host media"
            ),
            SyncPlanAction.ATTENTION: self.tr(
                "Unresolved matches · excluded from Sync"
            ),
            SyncPlanAction.UNCHANGED: self.tr("No changes needed"),
        }
        if self._replaces_payload is False:
            title = self.tr("Update Metadata")
            description = self.tr(
                "Sync tags, artwork, or ratings while keeping the audio and video"
            )
        else:
            title = titles[self.action, self.media]
            description = descriptions[self.action]
        self._title.setText(title)
        self._subtitle.setText(description)
        self.checkbox.setAccessibleName(self.tr("Select %1").replace("%1", title))
        self.checkbox.setToolTip(
            self.tr("Select or deselect all matching items in this group")
        )
        self.table.setAccessibleName(self.tr("%1 details").replace("%1", title))
        self.set_expanded(self.toggle.isChecked())
        self.refresh()


__all__ = ["SyncReviewGroup"]
