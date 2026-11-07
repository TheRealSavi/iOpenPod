"""An inline album band preserves card positions and batched grid formation."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.delegates.inline_album_delegate import InlineAlbumDelegate
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class _CardDelegate(QStyledItemDelegate):
    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(160, 200)


def test_expansion_moves_later_rows_and_preserves_batches_and_selection() -> None:
    source = QStandardItemModel()
    for row in range(180):
        source.appendRow(QStandardItem(f"Album {row}"))
    view = EqualizedGridView()
    view.setModel(source)
    cards = _CardDelegate(view)
    delegate = InlineAlbumDelegate(cards, view)
    view.setItemDelegate(delegate)
    view.synchronize_item_size()
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setLayoutMode(QListView.LayoutMode.Batched)
    view.setBatchSize(64)
    view.setMovement(QListView.Movement.Static)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.set_sectioned_layout(True)
    view.resize(900, 640)
    try:
        view.show()
        QTest.qWait(50)
        before = [view.visualRect(source.index(row, 0)) for row in range(180)]
        columns = next(row for row, rect in enumerate(before) if rect.top() > 0)
        first = columns
        last = columns * 2 - 1
        selected = source.index(first + 1, 0)
        view.setCurrentIndex(selected)
        selected_before = view.selectionModel().selectedIndexes()

        delegate.configure_expansion(first, last, 156)
        view.doItemsLayout()
        QTest.qWait(50)

        assert view.selectionModel().selectedIndexes() == selected_before
        for row, original in enumerate(before):
            current = view.visualRect(source.index(row, 0))
            assert current.left() == original.left()
            assert current.width() == original.width()
            assert current.top() == original.top() + (156 if row > last else 0)
            assert current.height() == original.height() + (
                156 if first <= row <= last else 0
            )
        option = QStyleOptionViewItem()
        assert delegate.sizeHint(option, QModelIndex()) == QSize(160, 200)
        view.synchronize_item_size()
        assert (
            delegate.normal_cell_size(option, selected).height() == before[0].height()
        )

        delegate.configure_expansion(-1, -1, 0)
        view.doItemsLayout()
        QTest.qWait(50)
        assert [view.visualRect(source.index(row, 0)) for row in range(180)] == before
        assert view.model() is source
    finally:
        view.close()
        APPLICATION.processEvents()
