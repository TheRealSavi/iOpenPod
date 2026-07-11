from __future__ import annotations

from PyQt6.QtCore import QRect, QSize
from PyQt6.QtWidgets import QLayout, QLayoutItem


class FlowLayout(QLayout):
    """Left-aligned, wrapping flow layout for fixed-size child widgets."""

    def __init__(self, parent=None, spacing: int = 0):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, a0: QLayoutItem | None) -> None:
        if a0 is not None:
            self._items.append(a0)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def spacing(self) -> int:
        return self._spacing

    def setSpacing(self, a0: int) -> None:
        self._spacing = a0

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, a0: int) -> int:
        return self._do_layout(a0, dry_run=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        width = 0
        height = 0
        for item in self._items:
            size_hint = item.sizeHint()
            width = max(width, size_hint.width())
            height = max(height, size_hint.height())
        margins = self.contentsMargins()
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def setGeometry(self, a0) -> None:
        super().setGeometry(a0)
        self._do_layout(a0.width(), dry_run=False)

    def _do_layout(self, width: int, *, dry_run: bool) -> int:
        margins = self.contentsMargins()
        x = margins.left()
        y = margins.top()
        right_edge = width - margins.right()
        row_height = 0
        spacing = self._spacing

        for item in self._items:
            size_hint = item.sizeHint()
            if x + size_hint.width() > right_edge and x > margins.left():
                x = margins.left()
                y += row_height + spacing
                row_height = 0

            if not dry_run:
                item.setGeometry(QRect(x, y, size_hint.width(), size_hint.height()))

            x += size_hint.width() + spacing
            row_height = max(row_height, size_hint.height())

        return y + row_height + margins.bottom()
