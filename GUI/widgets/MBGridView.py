import logging
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QSizePolicy
from .MBGridViewItem import MusicBrowserGridItem

log = logging.getLogger(__name__)


class MusicBrowserGrid(QFrame):
    """Grid view that displays albums, artists, or genres as clickable items."""
    item_selected = pyqtSignal(dict)  # Emits when an item is clicked

    def __init__(self):
        super().__init__()
        self.gridLayout = QGridLayout(self)
        self.gridLayout.setContentsMargins(10, 10, 10, 10)
        self.gridLayout.setSpacing(12)
        self.gridLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Allow the widget to shrink below the layout's natural minimum.
        # Without this, QGridLayout prevents shrinking inside a QScrollArea,
        # so resizeEvent never fires when the window gets narrower.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.gridItems = []  # Already added items
        self.pendingItems = []  # Items waiting to be added
        self.timerActive = False  # Prevent duplicate timers
        self.columnCount = 1  # Default column count
        self._current_category = "Albums"  # Current display category
        self._load_id = 0  # Incremented on each load to invalidate stale timers

    def loadCategory(self, category: str):
        """Load and display items for the specified category."""
        from ..app import iTunesDBCache, build_album_list, build_artist_list, build_genre_list
        log.debug(f"loadCategory() called: {category}")

        self._current_category = category
        self.clearGrid()

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return  # Data not ready yet

        # Get the appropriate data for this category
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
        log.debug(f"populateGrid() called with {len(items)} items")
        # Clear existing items first
        self.clearGrid()

        # Increment load ID to invalidate any pending timers from previous loads
        self._load_id += 1
        current_load_id = self._load_id

        # Recalculate column count (180px item + 12px spacing)
        self.columnCount = max(1, self._get_available_width() // (180 + 12))
        self._update_margins()

        # Reset pendingItems for fresh load
        self.pendingItems = list(enumerate(items))

        # Start incremental loading if not active
        if self.pendingItems and not self.timerActive:
            self.timerActive = True
            self._startAddingItems(current_load_id)

    def _startAddingItems(self, load_id: int):
        """Start the incremental item adding process."""
        self._addNextItem(load_id)

    def _addNextItem(self, load_id: int):
        """Add the next item, checking if this load is still valid."""
        # Check if this load has been superseded by a new one
        if load_id != self._load_id:
            self.timerActive = False
            return

        if not self.pendingItems:
            self.timerActive = False
            return

        # Add items in small batches for better performance
        batch_size = 5
        for _ in range(batch_size):
            if not self.pendingItems:
                break

            i, item = self.pendingItems.pop(0)
            row = i // self.columnCount
            col = i % self.columnCount

            if isinstance(item, dict):
                # Support both old format (album/artist) and new format (title/subtitle)
                title = item.get("title") or item.get("album", "Unknown")
                subtitle = item.get("subtitle") or item.get("artist", "")
                mhiiLink = item.get("mhiiLink")

                # Build item_data for click handling
                item_data = {
                    "title": title,
                    "subtitle": subtitle,
                    "mhiiLink": mhiiLink,
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
                continue  # Skip invalid items instead of raising

            self.gridLayout.addWidget(gridItem, row, col)

        # Schedule next batch if there are more items and load is still valid
        if self.pendingItems and load_id == self._load_id:
            QTimer.singleShot(8, lambda: self._addNextItem(load_id))
        else:
            self.timerActive = False

    def _onItemClicked(self, item_data: dict):
        """Handle grid item click."""
        self.item_selected.emit(item_data)

    def _get_available_width(self) -> int:
        """Get the available width for column calculations.

        When inside a QScrollArea, the grid widget's own width may not
        decrease (the layout minimum holds it), but the viewport always
        reflects the actual available space.
        """
        parent = self.parent()
        if parent:
            return parent.width()
        return self.width()

    def _update_margins(self):
        """Distribute leftover horizontal space as side padding so items stay centered."""
        available = self._get_available_width()
        used = self.columnCount * 180 + max(0, self.columnCount - 1) * 12
        leftover = max(0, available - used)
        side = leftover // 2
        self.gridLayout.setContentsMargins(side, 10, side, 10)

    def rearrangeGrid(self):
        """Rearrange grid items based on the new column count without clearing them."""
        if not self.gridItems:
            return

        self.columnCount = max(1, self._get_available_width() // (180 + 12))
        self._update_margins()

        for i, gridItem in enumerate(self.gridItems):
            row = i // self.columnCount
            col = i % self.columnCount
            self.gridLayout.addWidget(gridItem, row, col)

    def clearGrid(self):
        """Clear all grid items to prepare for reloading."""
        log.debug(f"clearGrid() called, current items: {len(self.gridItems)}, load_id: {self._load_id}")
        self.timerActive = False
        self.pendingItems = []
        # Increment load_id to invalidate any pending timer callbacks
        self._load_id += 1
        log.debug(f"  New load_id: {self._load_id}")

        # Remove all widgets from layout
        widget_count = self.gridLayout.count()
        log.debug(f"  Removing {widget_count} widgets from layout")
        while self.gridLayout.count():
            item = self.gridLayout.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    # Call cleanup to mark destroyed and disconnect signals
                    if isinstance(widget, MusicBrowserGridItem):
                        widget.cleanup()
                    widget.deleteLater()
        log.debug("  clearGrid() complete")

        self.gridItems = []

    def resizeEvent(self, a0):
        newCols = max(1, self._get_available_width() // (180 + 12))
        if self.columnCount != newCols:
            self.rearrangeGrid()
        else:
            self._update_margins()

        super().resizeEvent(a0)
