"""Read-only Host Media Library presentation through the shared Library widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QAbstractItemView

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.host_media_library import (
    HostMediaArtworkLoader,
    HostMediaLibrary,
    HostMediaPhotoLoader,
)
from iOpenPod.app.models.album_list_model import AlbumListModel
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
)
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.pages.track_page import TrackPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_detail import CollectionDetailPage
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.sync_selection_actions import SyncSelectionActions
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.models.sync_selection import SyncSelection
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager

type _HostLibraryPage = (
    LibraryPage | CollectionPage | TrackPage | PlaylistPage | PhotoPage
)


class HostLibraryBrowser:
    """Own one source-isolated, read-only copy of the Library browser surfaces."""

    def __init__(
        self,
        settings: SettingsService,
        theme_manager: ThemeManager,
        _device_artwork_provider: ArtworkPixmapProvider,
        workspace: LibraryWorkspace,
        parent: QStackedWidget,
        selection: SyncSelection | None = None,
    ) -> None:
        self.workspace = workspace
        self.track_model = TrackTableModel(parent)
        self.album_model = AlbumListModel(self.track_model, parent)
        self.artist_model = CollectionListModel(
            self.track_model,
            CollectionKind.ARTIST,
            parent,
        )
        self.genre_model = CollectionListModel(
            self.track_model,
            CollectionKind.GENRE,
            parent,
        )
        self.tv_show_model = CollectionListModel(
            self.track_model,
            CollectionKind.TV_SHOW,
            parent,
        )
        self.music_video_model = CollectionListModel(
            self.track_model,
            CollectionKind.MUSIC_VIDEO_ALBUM,
            parent,
        )
        if selection is not None:
            self.track_model.set_sync_selection(selection)
            self.album_model.set_sync_selection(selection)
            self.artist_model.set_sync_selection(selection)
            self.genre_model.set_sync_selection(selection)
            self.tv_show_model.set_sync_selection(selection)
            self.music_video_model.set_sync_selection(selection)
        self._photo_loader = HostMediaPhotoLoader()
        self._photo_controller = PhotoController(self._photo_loader, parent)
        self.photo_provider = PhotoPixmapProvider(self._photo_controller, parent)
        self._artwork_loader = HostMediaArtworkLoader()
        self._artwork_controller = ArtworkController(self._artwork_loader, parent)
        self.artwork_provider = ArtworkPixmapProvider(
            self._artwork_controller,
            parent,
        )
        self.library: HostMediaLibrary | None = None

        albums = LibraryPage(
            self.track_model,
            self.album_model,
            settings,
            theme_manager,
            self.artwork_provider,
            parent,
            selection_mode=selection is not None,
            follow_ipod_view_mode=False,
        )
        tracks = TrackPage(
            self.track_model,
            settings,
            theme_manager,
            self.artwork_provider,
            PageId.TRACKS,
            "host-tracks",
            None,
            parent,
        )
        artists = CollectionPage(
            self.track_model,
            self.artist_model,
            settings,
            theme_manager,
            self.artwork_provider,
            page_id=PageId.ARTISTS,
            table_id="host-artists-tracks",
            albums=self.album_model,
            parent=parent,
            selection_mode=selection is not None,
            follow_ipod_view_mode=False,
        )
        genres = CollectionPage(
            self.track_model,
            self.genre_model,
            settings,
            theme_manager,
            self.artwork_provider,
            page_id=PageId.GENRES,
            table_id="host-genres-tracks",
            albums=self.album_model,
            parent=parent,
            selection_mode=selection is not None,
            follow_ipod_view_mode=False,
        )
        audiobooks = TrackPage(
            self.track_model,
            settings,
            theme_manager,
            self.artwork_provider,
            PageId.AUDIOBOOKS,
            "host-audiobooks",
            (MediaKind.AUDIOBOOK,),
            parent,
        )
        movies = TrackPage(
            self.track_model,
            settings,
            theme_manager,
            self.artwork_provider,
            PageId.MOVIES,
            "host-movies",
            (MediaKind.MOVIE,),
            parent,
        )
        tv_shows = CollectionPage(
            self.track_model,
            self.tv_show_model,
            settings,
            theme_manager,
            self.artwork_provider,
            page_id=PageId.TV_SHOWS,
            table_id="host-tv-shows-tracks",
            parent=parent,
            selection_mode=selection is not None,
            follow_ipod_view_mode=False,
        )
        music_videos = CollectionPage(
            self.track_model,
            self.music_video_model,
            settings,
            theme_manager,
            self.artwork_provider,
            page_id=PageId.MUSIC_VIDEOS,
            table_id="host-music-videos-tracks",
            parent=parent,
            selection_mode=selection is not None,
            follow_ipod_view_mode=False,
        )
        videos = TrackPage(
            self.track_model,
            settings,
            theme_manager,
            self.artwork_provider,
            PageId.VIDEOS,
            "host-videos",
            (MediaKind.MOVIE, MediaKind.TV_SHOW, MediaKind.MUSIC_VIDEO),
            parent,
        )
        podcasts = TrackPage(
            self.track_model,
            settings,
            theme_manager,
            self.artwork_provider,
            PageId.PODCASTS,
            "host-podcasts",
            (MediaKind.PODCAST,),
            parent,
        )
        self.playlist_page = PlaylistPage(
            self.workspace,
            settings,
            theme_manager,
            self.artwork_provider,
            parent,
            source_actions=False,
        )
        self.photo_page = PhotoPage(
            self.workspace,
            settings,
            theme_manager,
            self.photo_provider,
            parent,
            source_actions=False,
            selection_mode=selection is not None,
        )
        if selection is not None:
            self.playlist_page.set_sync_selection(selection)
            self.photo_page.set_sync_selection(selection)
        self.page_widgets: dict[PageId, _HostLibraryPage] = {
            PageId.ALBUMS: albums,
            PageId.ARTISTS: artists,
            PageId.GENRES: genres,
            PageId.TRACKS: tracks,
            PageId.PLAYLISTS: self.playlist_page,
            PageId.PHOTOS: self.photo_page,
            PageId.PODCASTS: podcasts,
            PageId.AUDIOBOOKS: audiobooks,
            PageId.MOVIES: movies,
            PageId.TV_SHOWS: tv_shows,
            PageId.MUSIC_VIDEOS: music_videos,
            PageId.VIDEOS: videos,
        }
        self.pages: tuple[_HostLibraryPage, ...] = tuple(self.page_widgets.values())
        self._sync_actions = (
            SyncSelectionActions(selection, parent) if selection is not None else None
        )

        for page in self.pages:
            if selection is not None:
                for detail in page.findChildren(CollectionDetailPage):
                    detail.tracksCheckRequested.connect(selection.set_tracks_checked)
            for table in page.findChildren(TrackTable):
                if selection is None:
                    table.set_library_workspace(self.workspace)
                else:
                    table.setDragEnabled(False)
                    table.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            for grid in (
                *page.findChildren(AlbumGridView),
                *page.findChildren(CollectionGridView),
            ):
                if selection is None:
                    grid.set_library_workspace(self.workspace)
                else:
                    grid.setDragEnabled(False)
                    grid.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            if self._sync_actions is not None:
                for view in (
                    *page.findChildren(TrackTable),
                    *page.findChildren(AlbumGridView),
                    *page.findChildren(CollectionGridView),
                    *page.findChildren(PhotoGridView),
                ):
                    self._sync_actions.install(view)

    def load(self, library: HostMediaLibrary) -> None:
        """Publish a complete scan to every shared Host Library view model."""

        self.library = library
        self._artwork_loader.replace_library(library)
        self._artwork_controller.invalidate()
        self._photo_loader.replace_library(library)
        self._photo_controller.invalidate()
        self.workspace.load(library.snapshot)
        self.track_model.reset_tracks(library.snapshot.tracks)

    def retranslate(self) -> None:
        for model in (
            self.track_model,
            self.album_model,
            self.artist_model,
            self.genre_model,
            self.tv_show_model,
            self.music_video_model,
        ):
            model.retranslate()
        for page in self.pages:
            page.retranslate_ui()

    def shutdown(self) -> None:
        self.artwork_provider.shutdown()
        self._artwork_controller.shutdown()
        self.photo_provider.shutdown()
        self._photo_controller.shutdown()


__all__ = ["HostLibraryBrowser"]
