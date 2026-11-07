"""Reserve an inline detail band beneath one complete row of album cards."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class InlineAlbumDelegate(QStyledItemDelegate):
    """Grow existing cells without replacing album identities or selection."""

    def __init__(
        self,
        item_delegate: QAbstractItemDelegate,
        parent: EqualizedGridView,
    ) -> None:
        super().__init__(parent)
        self._item_delegate = item_delegate
        self._view = parent
        self._first_row = -1
        self._last_row = -1
        self._height = 0

    def configure_expansion(self, first: int, last: int, height: int) -> None:
        """Set the visual row's source bounds; the owner schedules relayout."""

        self._first_row = first
        self._last_row = last
        self._height = max(0, height) if 0 <= first <= last else 0

    def normal_cell_size(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        """Return card-cell geometry without the reserved detail band."""

        size = self._item_delegate.sizeHint(option, index)
        return (
            self._view.sectioned_item_size(size)
            if self._view.sectioned_layout
            else size
        )

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        if not index.isValid():
            # EqualizedGridView probes an invalid index for the unpadded card
            # size when fonts change. Feeding cell padding back grows the grid.
            return self._item_delegate.sizeHint(option, index)
        size = self.normal_cell_size(option, index)
        if self._expanded(index):
            size.setHeight(size.height() + self._height)
        return size

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        self._item_delegate.paint(painter, self._card_option(option, index), index)

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        return self._item_delegate.editorEvent(
            event, model, self._card_option(option, index), index
        )

    def _card_option(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QStyleOptionViewItem:
        card_option = QStyleOptionViewItem(option)
        if self._expanded(index):
            card_option.rect.setHeight(self.normal_cell_size(option, index).height())
        return card_option

    def _expanded(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        return index.isValid() and self._first_row <= index.row() <= self._last_row


__all__ = ["InlineAlbumDelegate"]
