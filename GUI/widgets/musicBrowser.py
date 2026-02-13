import logging
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QScrollArea, QFrame, QSplitter, QVBoxLayout, QSizePolicy
from .MBGridView import MusicBrowserGrid
from .MBListView import MusicBrowserList
from .trackListTitleBar import TrackListTitleBar
from ..styles import Colors

log = logging.getLogger(__name__)


class MusicBrowser(QFrame):
    """Main browser widget with grid and track list views."""

    def __init__(self):
        super().__init__()
        self._current_category = "Albums"

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        self.gridTrackSplitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Grid Browser in scroll area
        self.browserGrid = MusicBrowserGrid()
        self.browserGrid.item_selected.connect(self._onGridItemSelected)

        self.browserGridScroll = QScrollArea()
        self.browserGridScroll.setWidgetResizable(True)
        self.browserGridScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browserGridScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browserGridScroll.setMinimumHeight(0)
        self.browserGridScroll.setMinimumWidth(0)
        self.browserGridScroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserGridScroll.minimumSizeHint = lambda: QSize(0, 0)
        self.browserGridScroll.setWidget(self.browserGrid)
        self.browserGridScroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        self.gridTrackSplitter.addWidget(self.browserGridScroll)

        # Bottom: Track Browser
        self.trackContainer = QFrame()
        self.trackContainerLayout = QVBoxLayout(self.trackContainer)
        self.trackContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.trackContainerLayout.setSpacing(0)

        self.browserTrack = MusicBrowserList()
        self.browserTrack.setMinimumHeight(0)
        self.browserTrack.setMinimumWidth(0)
        self.browserTrack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserTrack.minimumSizeHint = lambda: QSize(0, 0)

        # Track Browser TitleBar
        self.trackListTitleBar = TrackListTitleBar(self.gridTrackSplitter)
        self.trackContainerLayout.addWidget(self.trackListTitleBar)
        self.trackContainerLayout.addWidget(self.browserTrack)

        self.gridTrackSplitter.addWidget(self.trackContainer)

        # Splitter properties
        handle = self.gridTrackSplitter.handle(1)
        if handle:
            handle.setEnabled(True)
        self.gridTrackSplitter.setCollapsible(0, True)
        self.gridTrackSplitter.setCollapsible(1, True)
        self.gridTrackSplitter.setHandleWidth(3)
        self.gridTrackSplitter.setStretchFactor(0, 2)
        self.gridTrackSplitter.setStretchFactor(1, 1)
        self.gridTrackSplitter.setMinimumSize(0, 0)
        self.gridTrackSplitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {Colors.BORDER_SUBTLE};
            }}
            QSplitter::handle:hover {{
                background: {Colors.ACCENT};
            }}
            QSplitter::handle:pressed {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)

        # Set initial sizes (60% grid, 40% tracks)
        self.gridTrackSplitter.setSizes([600, 400])

        self.mainLayout.addWidget(self.gridTrackSplitter)

    def reloadData(self):
        """Reload data from the current device."""
        self.browserGrid.clearGrid()
        self.browserTrack.clearTable()
        # Data will be loaded when cache emits data_ready

    def onDataReady(self):
        """Called when iTunesDB cache is loaded. Refresh current view."""
        self._refreshCurrentCategory()

    def updateCategory(self, category: str):
        """Update the display for the selected category."""
        log.debug(f"updateCategory() called: {category}")
        self._current_category = category
        self._refreshCurrentCategory()

    def _refreshCurrentCategory(self):
        """Refresh display based on current category and cache state."""
        log.debug(f"_refreshCurrentCategory() called: {self._current_category}")
        from ..app import iTunesDBCache
        cache = iTunesDBCache.get_instance()

        # Don't do anything if cache isn't ready yet
        if not cache.is_ready():
            log.debug("  Cache not ready, returning")
            return

        category = self._current_category

        if category == "Tracks":
            log.debug("  Showing Tracks view")
            # Hide grid, show all tracks
            self.browserGridScroll.hide()
            self.browserGrid.clearGrid()  # Clear grid to cancel pending image loads
            self.browserTrack.clearTable()  # Clear track list before reloading
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks()
            self.trackListTitleBar.setTitle("All Tracks")
            self.trackListTitleBar.resetColor()
        elif category == "Playlists":
            log.debug("  Showing Playlists view")
            # TODO: Implement playlist support
            self.browserGridScroll.show()
            self.browserGrid.clearGrid()
            self.trackListTitleBar.setTitle("Playlists - Coming Soon")
            self.trackListTitleBar.resetColor()
        else:
            log.debug(f"  Showing grid view for: {category}")
            # Show grid for Albums, Artists, Genres
            self.browserGridScroll.show()
            self.browserGrid.loadCategory(category)
            # Clear track list filter - user needs to select an item
            self.browserTrack.clearFilter()
            self.trackListTitleBar.setTitle(f"Select a{'n' if category[0] in 'AE' else ''} {category[:-1]}")
            self.trackListTitleBar.resetColor()

    def _onGridItemSelected(self, item_data: dict):
        """Handle when a grid item is clicked."""
        log.debug(f"_onGridItemSelected: {item_data.get('title', 'unknown')}")
        category = item_data.get("category", "Albums")
        title = item_data.get("title", "")
        filter_key = item_data.get("filter_key")
        filter_value = item_data.get("filter_value")

        # Update title bar with album color
        self.trackListTitleBar.setTitle(title)
        dominant_color = item_data.get("dominant_color")
        if dominant_color:
            r, g, b = dominant_color
            self.trackListTitleBar.setColor(r, g, b)
        else:
            self.trackListTitleBar.resetColor()

        # Apply filter to track list
        if filter_key and filter_value:
            log.debug(f"  Applying filter: {filter_key}={filter_value}")
            self.browserTrack.applyFilter(item_data)
        elif category == "Albums":
            album = item_data.get("album") or title
            artist = item_data.get("artist") or item_data.get("subtitle")
            self.browserTrack.filterByAlbum(album, artist)
        elif category == "Artists":
            self.browserTrack.filterByArtist(title)
        elif category == "Genres":
            self.browserTrack.filterByGenre(title)
