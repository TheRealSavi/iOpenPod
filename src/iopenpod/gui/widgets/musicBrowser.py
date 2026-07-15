from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
)

from iopenpod.itunesdb_shared.constants import (
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_MASK,
)

from ..styles import Colors, make_scroll_area
from .gridHeaderBar import GridHeaderBar
from .MBGridView import MusicBrowserGrid
from .MBListView import MusicBrowserList
from .photoBrowser import PhotoBrowserWidget
from .playlistBrowser import PlaylistBrowser
from .podcastBrowser import PodcastBrowser
from .trackContextMenu import (
    ChapteredAlbumMenuAction,
    resolve_grid_item_tracks,
    show_track_context_menu,
)
from .trackListTitleBar import TrackListTitleBar

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )


class MusicBrowser(QFrame):
    """Main browser widget with grid and track list views."""

    album_conversion_requested = pyqtSignal(list)
    track_activated = pyqtSignal(dict)
    playback_requested = pyqtSignal(dict, list, int)

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        libraries: LibraryService,
    ):
        super().__init__()
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_service = libraries
        self._library_cache: LibraryCacheLike = libraries.cache()
        self._current_category = "Albums"
        self._tab_dirty: dict[str, bool] = {
            "Playlists": True,
            "Podcasts": True,
            "Photos": True,
        }
        self._tab_loaded: dict[str, bool] = {
            "Playlists": False,
            "Podcasts": False,
            "Photos": False,
        }

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        self.gridTrackSplitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Header bar + Grid Browser in scroll area, wrapped in a container
        self.browserGrid = MusicBrowserGrid(
            device_sessions=self._device_sessions,
            library_cache=self._library_cache,
            settings_service=self._settings_service,
        )
        self.browserGrid.item_selected.connect(self._onGridItemSelected)
        self.browserGrid.item_context_requested.connect(self._onGridItemContextRequested)

        self.browserGridScroll = make_scroll_area()
        self.browserGridScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browserGridScroll.setMinimumHeight(0)
        self.browserGridScroll.setMinimumWidth(0)
        self.browserGridScroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserGridScroll.minimumSizeHint = lambda: QSize(0, 0)
        self.browserGridScroll.setWidget(self.browserGrid)
        self.browserGrid.attachScrollArea(self.browserGridScroll)

        self.gridHeaderBar = GridHeaderBar()
        self.gridHeaderBar.sort_changed.connect(
            lambda key, rev: self.browserGrid.setSort(key, rev)
        )
        self.gridHeaderBar.search_changed.connect(self.browserGrid.setSearchFilter)

        self.gridContainer = QFrame()
        self.gridContainer.setMinimumSize(0, 0)
        gridContainerLayout = QVBoxLayout(self.gridContainer)
        gridContainerLayout.setContentsMargins(0, 0, 0, 0)
        gridContainerLayout.setSpacing(0)
        gridContainerLayout.addWidget(self.gridHeaderBar)
        gridContainerLayout.addWidget(self.browserGridScroll)

        self.gridTrackSplitter.addWidget(self.gridContainer)

        # Bottom: Track Browser
        self.trackContainer = QFrame()
        self.trackContainerLayout = QVBoxLayout(self.trackContainer)
        self.trackContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.trackContainerLayout.setSpacing(0)

        self.browserTrack = MusicBrowserList(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            library_cache=self._library_cache,
            show_search_bar=False,
        )
        self.browserTrack.setMinimumHeight(0)
        self.browserTrack.setMinimumWidth(0)
        self.browserTrack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserTrack.minimumSizeHint = lambda: QSize(0, 0)
        self.browserTrack.track_activated.connect(self.track_activated.emit)
        self.browserTrack.playback_requested.connect(self.playback_requested.emit)

        # Track Browser TitleBar
        self.trackListTitleBar = TrackListTitleBar(self.gridTrackSplitter)
        self.trackListTitleBar.search_changed.connect(
            self.browserTrack.setSearchQuery
        )
        self.browserTrack.search_query_changed.connect(
            self.trackListTitleBar.setSearchQuery
        )
        self.trackContainerLayout.addWidget(self.trackListTitleBar)
        self.trackContainerLayout.addWidget(self.browserTrack)

        self.gridTrackSplitter.addWidget(self.trackContainer)

        # Splitter properties
        handle = self.gridTrackSplitter.handle(1)
        if handle:
            handle.setEnabled(True)
        self.gridTrackSplitter.setCollapsible(0, True)
        self.gridTrackSplitter.setCollapsible(1, True)
        self.gridTrackSplitter.setHandleWidth(0)
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
            saved = self._settings_service.get_effective_settings().splitter_sizes
            if isinstance(saved, list) and len(saved) == 2:
                self.gridTrackSplitter.setSizes([int(saved[0]), int(saved[1])])
            else:
                self.gridTrackSplitter.setSizes([600, 400])
        except Exception:
            self.gridTrackSplitter.setSizes([600, 400])

        # Persist splitter position on change
        self.gridTrackSplitter.splitterMoved.connect(self._save_splitter_sizes)

        # Playlist browser (shown when Playlists category is active)
        self.playlistBrowser = PlaylistBrowser(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            libraries=self._library_service,
        )
        self.playlistBrowser.track_activated.connect(self.track_activated.emit)
        self.playlistBrowser.playback_requested.connect(self.playback_requested.emit)

        # Podcast browser (shown when Podcasts category is active)
        self.podcastBrowser = PodcastBrowser(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            libraries=self._library_service,
        )
        self.photoBrowser = PhotoBrowserWidget(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            libraries=self._library_service,
        )

        # Use a stacked widget to toggle between grid/track and playlist views
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gridTrackSplitter)   # index 0
        self.stack.addWidget(self.playlistBrowser)      # index 1
        self.stack.addWidget(self.podcastBrowser)       # index 2
        self.stack.addWidget(self.photoBrowser)         # index 3

        self.mainLayout.addWidget(self.stack)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refreshCurrentCategory)

        self._bind_cache_signals()

    def _bind_cache_signals(self) -> None:
        """Mark heavy tabs dirty when cache-backed data changes."""
        try:
            cache = self._library_cache
            cache.playlists_changed.connect(self._on_playlists_changed)
            track_fields_changed = getattr(cache, "track_fields_changed", None)
            if track_fields_changed is not None:
                track_fields_changed.connect(self._on_track_fields_changed)
            else:
                cache.tracks_changed.connect(self._on_tracks_changed)
            cache.photos_changed.connect(lambda: self._mark_tab_dirty("Photos"))
        except Exception:
            pass

    def _on_playlists_changed(self) -> None:
        """Refresh the playlists view in place when playlist data changes."""
        self._mark_tab_dirty("Playlists")
        if self._current_category == "Playlists" and self._tab_loaded["Playlists"]:
            self.playlistBrowser.refreshFromCache()
            self._tab_dirty["Playlists"] = False

    def _on_tracks_changed(self) -> None:
        """Conservatively refresh for caches without field-aware signals."""
        self._mark_tab_dirty("Playlists")
        self._mark_tab_dirty("Podcasts")
        if self._current_category != "Photos":
            self._schedule_refresh_current_category()

    def _on_track_fields_changed(self, fields: object) -> None:
        """Apply track edits in place unless they change grid grouping or artwork."""
        self._mark_tab_dirty("Playlists")
        self._mark_tab_dirty("Podcasts")
        if self._current_category == "Photos":
            return

        field_values: Iterable[object]
        if isinstance(fields, (set, frozenset, list, tuple)):
            field_values = fields
        else:
            field_values = ()
        changed_fields = {
            str(field).strip().lower().replace("-", "_").replace(" ", "_")
            for field in field_values
        }
        grid_fields = {
            "album",
            "album_artist",
            "artist",
            "genre",
            "compilation",
            "compilation_flag",
            "artwork",
        }
        if changed_fields & grid_fields:
            self._schedule_refresh_current_category()
            return

        self.browserTrack._refresh_visible_rows()

    def _mark_tab_dirty(self, tab_name: str) -> None:
        if tab_name in self._tab_dirty:
            self._tab_dirty[tab_name] = True

    def _mark_all_tabs_dirty(self) -> None:
        for tab_name in self._tab_dirty:
            self._tab_dirty[tab_name] = True

    def _schedule_refresh_current_category(self) -> None:
        """Coalesce rapid category/data changes into one UI refresh tick."""
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    def reloadData(self):
        """Reload data from the current device."""
        self.browserGrid.clearGrid()
        self.browserTrack.clearTable(clear_cache=True)
        self.playlistBrowser.clear()
        self.podcastBrowser.clear()
        self.photoBrowser.clear()
        for tab_name in self._tab_loaded:
            self._tab_loaded[tab_name] = False
        self._mark_all_tabs_dirty()
        # Data will be loaded when cache emits data_ready

    def _save_splitter_sizes(self):
        """Persist the current splitter sizes to settings."""
        try:
            s = self._settings_service.get_global_settings()
            s.splitter_sizes = list(self.gridTrackSplitter.sizes())
            self._settings_service.save_global_settings(s)
        except Exception:
            log.debug("Failed to save splitter sizes", exc_info=True)

    def _apply_constrained_splitter_sizes(self):
        """Apply splitter sizing with constraint: track list <= 50% of window height.

        Uses the entire window height (not just splitter) to ensure consistent
        sizing regardless of current layout state. Prevents track list from
        taking more than 50% of window height, ensuring grid stays visible.
        """
        try:
            saved = self._settings_service.get_effective_settings().splitter_sizes
            if isinstance(saved, list) and len(saved) == 2:
                grid_h, track_h = int(saved[0]), int(saved[1])
            else:
                grid_h, track_h = 600, 400
        except Exception:
            grid_h, track_h = 600, 400

        # Calculate 50% based on entire window height
        window = self.window()
        window_h = window.height() if window else 800
        max_track = window_h // 2

        # Constraint: track list should not exceed 50% of window height
        if track_h > max_track:
            track_h = max_track
            grid_h = window_h - track_h

        self.gridTrackSplitter.setSizes([grid_h, track_h])

    def _show_track_list_fullscreen(self) -> None:
        """Give the track list all splitter space when the grid pane is hidden."""

        for widget_name in ("trackContainer", "browserTrack"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.show()

        sizes = self.gridTrackSplitter.sizes()
        total = max(self.gridTrackSplitter.height(), sum(sizes), 1)
        self.gridTrackSplitter.setSizes([0, total])

    def onDataReady(self):
        """Called when iTunesDB cache is loaded. Refresh current view."""
        self._mark_all_tabs_dirty()
        self._schedule_refresh_current_category()

    def updateCategory(self, category: str):
        """Update the display for the selected category."""
        self._current_category = category
        self._schedule_refresh_current_category()

    def _refreshCurrentCategory(self):
        """Refresh display based on current category and cache state."""
        cache = self._library_cache

        # Don't do anything if cache isn't ready yet
        if not cache.is_ready():
            return

        category = self._current_category

        if category == "Tracks":
            self.stack.setCurrentIndex(0)
            # Hide entire grid container (header + grid) for fullscreen tracklist
            self.gridContainer.hide()
            self.browserGrid.clearGrid()  # Clear grid to cancel pending image loads
            self.browserTrack.clearTable()  # Clear track list before reloading
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=MEDIA_TYPE_AUDIO)
            self.trackListTitleBar.setTitle("All Tracks")
            self.trackListTitleBar.resetColor()
            self.trackListTitleBar.setFullscreenMode(True)
            self._show_track_list_fullscreen()
        elif category == "Playlists":
            self.stack.setCurrentIndex(1)
            self.trackListTitleBar.setFullscreenMode(False)
            if self._tab_dirty["Playlists"] or not self._tab_loaded["Playlists"]:
                self.playlistBrowser.loadPlaylists()
                self._tab_dirty["Playlists"] = False
                self._tab_loaded["Playlists"] = True
        elif category == "Podcasts":
            # Podcast manager — full subscription browser
            self.stack.setCurrentIndex(2)
            self.trackListTitleBar.setFullscreenMode(False)
            if self._tab_dirty["Podcasts"] or not self._tab_loaded["Podcasts"]:
                self._ensure_podcast_device()
                self._tab_dirty["Podcasts"] = False
                self._tab_loaded["Podcasts"] = True
        elif category == "Photos":
            self.stack.setCurrentIndex(3)
            self.trackListTitleBar.setFullscreenMode(False)
            if self._tab_dirty["Photos"] or not self._tab_loaded["Photos"]:
                self.photoBrowser.reload()
                self._tab_dirty["Photos"] = False
                self._tab_loaded["Photos"] = True
        elif category == "Audiobooks":
            # Non-music audio categories — hide entire grid container for fullscreen tracklist
            log.debug(f"  Showing {category} view")
            self.stack.setCurrentIndex(0)
            self.gridContainer.hide()
            self.browserGrid.clearGrid()
            self.browserTrack.clearTable()
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=MEDIA_TYPE_AUDIOBOOK)
            self.trackListTitleBar.setTitle(category)
            self.trackListTitleBar.resetColor()
            self.trackListTitleBar.setFullscreenMode(True)
            self._show_track_list_fullscreen()
        elif category in ("Videos", "Movies", "TV Shows", "Music Videos"):
            # Video categories: hide entire grid container for fullscreen tracklist
            _MEDIA_TYPE_FILTER = {
                "Videos": MEDIA_TYPE_VIDEO_MASK,
                "Movies": MEDIA_TYPE_VIDEO,
                "TV Shows": MEDIA_TYPE_TV_SHOW,
                "Music Videos": MEDIA_TYPE_MUSIC_VIDEO,
            }
            self.stack.setCurrentIndex(0)
            self.gridContainer.hide()
            self.browserGrid.clearGrid()
            self.browserTrack.clearTable()
            self.browserTrack.clearFilter()
            self.browserTrack.loadTracks(media_type_filter=_MEDIA_TYPE_FILTER[category])
            self.trackListTitleBar.setTitle(category)
            self.trackListTitleBar.resetColor()
            self.trackListTitleBar.setFullscreenMode(True)
            self._show_track_list_fullscreen()
        else:
            self.stack.setCurrentIndex(0)
            # Show grid for Albums, Artists, Genres
            self.gridContainer.show()
            self.gridHeaderBar.setCategory(category)
            self.gridHeaderBar.resetState()

            self.browserGrid.resetFilters()
            self.browserGrid.loadCategory(category)
            # Pre-load audio-only tracks so filterByAlbum/Artist/Genre
            # won't include video tracks in results.
            self.browserTrack.loadTracks(media_type_filter=MEDIA_TYPE_AUDIO)
            self.browserTrack.clearFilter()
            self.trackListTitleBar.setTitle(f"Select a{'n' if category[0] in 'AE' else ''} {category[:-1]}")
            self.trackListTitleBar.resetColor()
            self.trackListTitleBar.setFullscreenMode(False)

            # Apply constrained splitter sizes (50% grid max, 50% track list min)
            self._apply_constrained_splitter_sizes()

    def _onGridItemSelected(self, item_data: dict):
        """Handle when a grid item is clicked."""
        category = item_data.get("category", "Albums")
        title = item_data.get("title", "")
        filter_key = item_data.get("filter_key")
        filter_value = item_data.get("filter_value")

        # Update title bar with album color
        self.trackListTitleBar.setTitle(title)
        display_dominant_color = item_data.get("display_dominant_color")
        dominant_color = display_dominant_color or item_data.get("dominant_color")
        if dominant_color:
            r, g, b = dominant_color
            album_colors = item_data.get("display_album_colors") or item_data.get("album_colors", {})
            text = album_colors.get("text")
            text_sec = album_colors.get("text_secondary")
            self.trackListTitleBar.setColor(
                r,
                g,
                b,
                text=text,
                text_secondary=text_sec,
                contrast_ensured=display_dominant_color is not None,
            )
        else:
            self.trackListTitleBar.resetColor()

        # Apply filter to track list
        if filter_key is not None and filter_value is not None:
            self.browserTrack.applyFilter(item_data)
        elif category == "Albums":
            album = item_data.get("album") or title
            artist = item_data.get("artist") or ""
            self.browserTrack.filterByAlbum(album, artist)
        elif category == "Artists":
            self.browserTrack.filterByArtist(title)
        elif category == "Genres":
            self.browserTrack.filterByGenre(title)

    def _onGridItemContextRequested(self, items: object, global_pos) -> None:
        """Show the shared track menu for grouped grid items."""
        if self._current_category not in {"Albums", "Artists", "Genres"}:
            return
        if not isinstance(items, list):
            return

        grid_items = [
            dict(item)
            for item in items
            if isinstance(item, dict)
            and item.get("category", self._current_category) == self._current_category
        ]
        if not grid_items:
            return

        selected_tracks = self._resolve_grid_tracks_for_menu(grid_items)
        if not selected_tracks:
            return

        if self._current_category == "Albums":
            show_track_context_menu(
                self,
                self.browserTrack,
                selected_tracks,
                global_pos,
                chaptered_album_action=ChapteredAlbumMenuAction(
                    items=tuple(grid_items),
                    requested=self.album_conversion_requested.emit,
                ),
            )
            return

        show_track_context_menu(
            self,
            self.browserTrack,
            selected_tracks,
            global_pos,
        )

    def _resolve_grid_tracks_for_menu(self, grid_items: list[dict]) -> list[dict]:
        cache = self._library_cache
        if cache is None or not cache.is_ready():
            return []

        all_tracks = cache.get_tracks()
        selected: list[dict] = []
        seen: set[int] = set()
        for item in grid_items:
            for track in resolve_grid_item_tracks(item, all_tracks):
                identity = id(track)
                if identity in seen:
                    continue
                seen.add(identity)
                selected.append(track)
        return selected

    def refresh_artwork_appearance(self) -> None:
        """Refresh list and grid artwork after an appearance setting changes."""
        self.browserGrid.refresh_artwork_appearance()
        self.browserTrack.refresh_artwork_appearance()
        self.playlistBrowser.trackList.refresh_artwork_appearance()
        self.photoBrowser.refresh_artwork_appearance()

    def _ensure_podcast_device(self):
        """Bind the podcast browser to the current iPod device if not done."""
        session = self._device_sessions.current_session()
        if not session.device_path:
            return

        device = session.discovered_ipod
        serial = (
            getattr(device, "serial", "")
            or getattr(device, "firewire_guid", "")
            or "_default"
        )
        self.podcastBrowser.set_device(serial, session.device_path)
