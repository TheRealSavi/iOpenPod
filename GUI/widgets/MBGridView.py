import logging
from collections import deque
from PyQt6.QtCore import QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLayout, QLayoutItem, QSizePolicy
from .MBGridViewItem import MusicBrowserGridItem
from ..styles import Metrics

log = logging.getLogger(__name__)


# ── Flow layout ──────────────────────────────────────────────────────────────
# Lays out fixed-size children left-to-right, wrapping to the next row.
# Items are always left-aligned; no centering hack needed.

class _FlowLayout(QLayout):
    """Left-aligned, wrapping flow layout for fixed-size grid items."""

    def __init__(self, parent=None, spacing: int = 0):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    # -- QLayout API --

    def addItem(self, a0: QLayoutItem | None):
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

    def setSpacing(self, a0: int):
        self._spacing = a0

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, a0: int) -> int:
        return self._do_layout(a0, dry_run=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        # Minimum: one item wide
        w = h = 0
        for item in self._items:
            sz = item.sizeHint()
            w = max(w, sz.width())
            h = max(h, sz.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def setGeometry(self, a0):
        super().setGeometry(a0)
        self._do_layout(a0.width(), dry_run=False)

    # -- Layout engine --

    def _do_layout(self, width: int, *, dry_run: bool) -> int:
        m = self.contentsMargins()
        x = m.left()
        y = m.top()
        right_edge = width - m.right()
        row_height = 0
        sp = self._spacing

        for item in self._items:
            sz = item.sizeHint()
            # Wrap to next row if this item exceeds the right edge
            if x + sz.width() > right_edge and x > m.left():
                x = m.left()
                y += row_height + sp
                row_height = 0

            if not dry_run:
                item.setGeometry(QRect(x, y, sz.width(), sz.height()))

            x += sz.width() + sp
            row_height = max(row_height, sz.height())

        return y + row_height + m.bottom()


class MusicBrowserGrid(QFrame):
    """Grid view that displays albums, artists, or genres as clickable items."""
    item_selected = pyqtSignal(dict)  # Emits when an item is clicked

    def __init__(self):
        super().__init__()
        self._flow = _FlowLayout(self, spacing=Metrics.GRID_SPACING)
        self._flow.setContentsMargins(Metrics.GRID_SPACING, Metrics.GRID_SPACING,
                                      Metrics.GRID_SPACING, Metrics.GRID_SPACING)

        # Allow the widget to shrink inside a QScrollArea.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.gridItems: list[MusicBrowserGridItem] = []
        self.pendingItems: deque = deque()
        self.timerActive = False
        self.columnCount = 1  # kept for external compat, not used by layout
        self._current_category = "Albums"
        self._load_id = 0

    def loadCategory(self, category: str):
        """Load and display items for the specified category."""
        from ..app import iTunesDBCache, build_album_list, build_artist_list, build_genre_list
        log.debug(f"loadCategory() called: {category}")

        self._current_category = category
        self.clearGrid()

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        if category == "Albums":
            items = build_album_list(cache)
        elif category == "Artists":
            items = build_artist_list(cache)
        elif category == "Genres":
            items = build_genre_list(cache)
        else:
            return

        self.populateGrid(items)

    def populateGrid(self, items):
        """Populate the grid with items."""
        self.clearGrid()
        self._load_id += 1
        current_load_id = self._load_id

        self.pendingItems = deque(enumerate(items))

        if self.pendingItems and not self.timerActive:
            self.timerActive = True
            self._addNextItem(current_load_id)

    def _addNextItem(self, load_id: int):
        """Add the next batch of items."""
        if load_id != self._load_id:
            self.timerActive = False
            return

        if not self.pendingItems:
            self.timerActive = False
            return

        batch_size = 5
        for _ in range(batch_size):
            if not self.pendingItems:
                break

            i, item = self.pendingItems.popleft()

            if isinstance(item, dict):
                title = item.get("title") or item.get("album", "Unknown")
                subtitle = item.get("subtitle") or item.get("artist", "")
                mhiiLink = item.get("artwork_id_ref")

                item_data = {
                    "title": title,
                    "subtitle": subtitle,
                    "artwork_id_ref": mhiiLink,
                    "category": item.get("category", "Albums"),
                    "filter_key": item.get("filter_key", "Album"),
                    "filter_value": item.get("filter_value", title),
                    "album": item.get("album"),
                    "artist": item.get("artist"),
                }

                gridItem = MusicBrowserGridItem(title, subtitle, mhiiLink, item_data)
                gridItem.clicked.connect(self._onItemClicked)
                self.gridItems.append(gridItem)
            elif isinstance(item, MusicBrowserGridItem):
                gridItem = item
                gridItem.clicked.connect(self._onItemClicked)
            else:
                continue

            self._flow.addWidget(gridItem)

        if self.pendingItems and load_id == self._load_id:
            QTimer.singleShot(8, lambda: self._addNextItem(load_id))
        else:
            self.timerActive = False

    def _onItemClicked(self, item_data: dict):
        """Handle grid item click."""
        self.item_selected.emit(item_data)

    def rearrangeGrid(self):
        """Trigger a re-layout (flow layout handles this automatically)."""
        self._flow.activate()

    def clearGrid(self):
        """Clear all grid items to prepare for reloading."""
        self.timerActive = False
        self.pendingItems = deque()
        self._load_id += 1

        while self._flow.count():
            item = self._flow.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    if isinstance(widget, MusicBrowserGridItem):
                        widget.cleanup()
                    widget.deleteLater()

        self.gridItems = []

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
