# Hallmark · component: Sync Review group · theme: iOpenPod
# pre-emit critique: P5 H5 E4 S5 R5 V4
"""Collapsible change groups with bounded, virtualized detail tables."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.sync_plan_table_model import (
    SyncPlanColumn,
    SyncPlanFilterModel,
    SyncPlanRole,
)
from iOpenPod.app.sync_plan import SyncPlanAction, SyncPlanItem, SyncPlanMediaKind
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncReviewGroup")
        self.setProperty("action", action.value)
        self.setProperty("media", media.value if media is not None else "all")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action = action
        self.media = media
        self._header_action = header_action
        self.proxy = SyncPlanFilterModel(self)
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
        self.table.setColumnWidth(SyncPlanColumn.REASON, 220)
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
        title = titles[self.action, self.media]
        self._title.setText(title)
        self._subtitle.setText(descriptions[self.action])
        self.checkbox.setAccessibleName(self.tr("Select %1").replace("%1", title))
        self.checkbox.setToolTip(
            self.tr("Select or deselect all matching items in this group")
        )
        self.table.setAccessibleName(self.tr("%1 details").replace("%1", title))
        self.set_expanded(self.toggle.isChecked())
        self.refresh()


__all__ = ["SyncReviewGroup"]
