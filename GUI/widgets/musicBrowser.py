import logging
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QScrollArea, QFrame, QSplitter, QVBoxLayout, QSizePolicy, QStackedWidget
from .MBGridView import MusicBrowserGrid
from .MBListView import MusicBrowserList
from .playlistBrowser import PlaylistBrowser
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

        # Set initial sizes (60% grid, 40% tracks) or restore from settings
        try:
            from ..settings import get_settings
            saved = get_settings().splitter_sizes
            if isinstance(saved, list) and len(saved) == 2:
                self.gridTrackSplitter.setSizes([int(saved[0]), int(saved[1])])
            else:
                self.gridTrackSplitter.setSizes([600, 400])
        except Exception:
            self.gridTrackSplitter.setSizes([600, 400])

        # Persist splitter position on change
        self.gridTrackSplitter.splitterMoved.connect(self._save_splitter_sizes)

        # Playlist browser (shown when Playlists category is active)
        self.playlistBrowser = PlaylistBrowser()

        # Use a stacked widget to toggle between grid/track and playlist views
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gridTrackSplitter)   # index 0
        self.stack.addWidget(self.playlistBrowser)      # index 1

        self.mainLayout.addWidget(self.stack)

    def reloadData(self):
        """Reload data from the current device."""
        self.browserGrid.clearGrid()
        self.browserTrack.clearTable()
        self.playlistBrowser.clear()
        # Data will be loaded when cache emits data_ready

    def _save_splitter_sizes(self):
        """Persist the current splitter sizes to settings."""
        try:
            from ..settings import get_settings
            s = get_settings()
            s.splitter_sizes = list(self.gridTrackSplitter.sizes())
            s.save()
        except Exception:
            pass

    def onDataReady(self):
        """Called when iTunesDB cache is loaded. Refresh current view."""
        self._refreshCurrentCategory()

    def updateCategory(self, category: str):
        """Update the display for the selected category."""
        self._current_category = category
        self._refreshCurrentCategory()

    def _refreshCurrentCategory(self):
        """Refresh display based on current category and cache state."""
        from ..app import iTunesDBCache
        cache = iTunesDBCache.get_instance()

        # Don't do anything if cache isn't ready yet
        if not cache.is_ready():
            return

        category = self._current_category

        if category == "Tracks":
            self.stack.setCurrentIndex(0)
            # Hide grid, show all tracks
            self.browserGridScroll.hide()
            self.browserGrid.clearGrid()  # Clear grid to cancel pending image loads
            self.browserTrack.clearTable()  # Clear track list before reloading
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=0x01)  # Audio only
            self.trackListTitleBar.setTitle("All Tracks")
            self.trackListTitleBar.resetColor()
        elif category == "Playlists":
            self.stack.setCurrentIndex(1)
            self.playlistBrowser.loadPlaylists()
        elif category in ("Podcasts", "Audiobooks"):
            # Non-music audio categories
            _NOMUSIC_FILTER = {
                "Podcasts": 0x04,      # MEDIA_TYPE_PODCAST (includes video podcast 0x06)
                "Audiobooks": 0x08,    # MEDIA_TYPE_AUDIOBOOK
            }
            log.debug(f"  Showing {category} view")
            self.stack.setCurrentIndex(0)
            self.browserGridScroll.hide()
            self.browserGrid.clearGrid()
            self.browserTrack.clearTable()
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=_NOMUSIC_FILTER[category])
            self.trackListTitleBar.setTitle(category)
            self.trackListTitleBar.resetColor()
        elif category in ("Videos", "Movies", "TV Shows", "Music Videos"):
            # Video categories: show track list filtered by media type
            _MEDIA_TYPE_FILTER = {
                "Videos": 0x62,        # All video (VIDEO|MUSIC_VIDEO|TV_SHOW)
                "Movies": 0x02,        # MEDIA_TYPE_VIDEO
                "TV Shows": 0x40,      # MEDIA_TYPE_TV_SHOW
                "Music Videos": 0x20,  # MEDIA_TYPE_MUSIC_VIDEO
            }
            self.stack.setCurrentIndex(0)
            self.browserGridScroll.hide()
            self.browserGrid.clearGrid()
            self.browserTrack.clearTable()
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=_MEDIA_TYPE_FILTER[category])
            self.trackListTitleBar.setTitle(category)
            self.trackListTitleBar.resetColor()
        else:
            self.stack.setCurrentIndex(0)
            # Show grid for Albums, Artists, Genres
            self.browserGridScroll.show()
            self.browserGrid.loadCategory(category)
            # Pre-load audio-only tracks so filterByAlbum/Artist/Genre
            # won't include video tracks in results.
            self.browserTrack.loadTracks(media_type_filter=0x01)
            self.browserTrack.clearFilter()
            self.trackListTitleBar.setTitle(f"Select a{'n' if category[0] in 'AE' else ''} {category[:-1]}")
            self.trackListTitleBar.resetColor()

    def _onGridItemSelected(self, item_data: dict):
        """Handle when a grid item is clicked."""
        category = item_data.get("category", "Albums")
        title = item_data.get("title", "")
        filter_key = item_data.get("filter_key")
        filter_value = item_data.get("filter_value")

        # Update title bar with album color
        self.trackListTitleBar.setTitle(title)
        dominant_color = item_data.get("dominant_color")
        if dominant_color:
            r, g, b = dominant_color
            album_colors = item_data.get("album_colors", {})
            text = album_colors.get("text")
            text_sec = album_colors.get("text_secondary")
            self.trackListTitleBar.setColor(r, g, b, text=text, text_secondary=text_sec)
        else:
            self.trackListTitleBar.resetColor()

        # Apply filter to track list
        if filter_key and filter_value:
            self.browserTrack.applyFilter(item_data)
        elif category == "Albums":
            album = item_data.get("album") or title
            artist = item_data.get("artist") or item_data.get("subtitle")
            self.browserTrack.filterByAlbum(album, artist)
        elif category == "Artists":
            self.browserTrack.filterByArtist(title)
        elif category == "Genres":
            self.browserTrack.filterByGenre(title)
