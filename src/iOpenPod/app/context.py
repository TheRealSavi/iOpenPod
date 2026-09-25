"""Application dependency composition."""

from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.backup_controller import BackupController
from iOpenPod.app.backups import BackupService
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    create_global_settings_store,
)
from iOpenPod.app.core.status import ApplicationStatus
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.host_media_controller import HostMediaScanController
from iOpenPod.app.host_media_library import HostMediaScanner
from iOpenPod.app.ipod_media_controller import IPodMediaScanController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write_controller import LibraryWriteController
from iOpenPod.app.lyrics_controller import LyricsController
from iOpenPod.app.models.album_list_model import AlbumListModel
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
)
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.app.playback.qt_backend import QtPlaybackBackend
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController
from iOpenPod.app.podcasts.controller import PodcastController
from iOpenPod.app.podcasts.feed_client import HttpPodcastArtworkLoader
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.synesthesia import SynesthesiaController, WholeTrackMusicAnalyzer
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from storage import Storage


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AppContext:
    """The explicit dependency graph for the application-shell prototype."""

    device_coordinator: DeviceCoordinator
    device_controller: DeviceController
    artwork_controller: ArtworkController
    photo_controller: PhotoController
    backup_controller: BackupController
    host_media_controller: HostMediaScanController
    ipod_media_controller: IPodMediaScanController
    playback_controller: PlaybackController
    lyrics_controller: LyricsController
    synesthesia_controller: SynesthesiaController
    podcast_controller: PodcastController
    podcast_artwork_controller: PodcastArtworkController
    status: ApplicationStatus
    library_workspace: LibraryWorkspace
    library_write_controller: LibraryWriteController
    track_model: TrackTableModel
    album_model: AlbumListModel
    artist_model: CollectionListModel
    genre_model: CollectionListModel
    tv_show_model: CollectionListModel
    music_video_model: CollectionListModel
    settings: SettingsService
    theme_manager: ThemeManager
    i18n_manager: I18nManager

    def __post_init__(self) -> None:
        self.library_workspace.tracksChanged.connect(self._workspace_tracks_changed)

    def _workspace_tracks_changed(self, _tracks: object) -> None:
        self.track_model.replace_tracks(self.library_workspace.tracks)

    @classmethod
    def create(cls, application: QApplication) -> "AppContext":
        storage = Storage()
        settings = SettingsService(
            create_global_settings_store(storage),
            DeviceSettingsStore(),
            application,
        )
        theme_manager = ThemeManager(application, settings, application)
        i18n_manager = I18nManager(application, settings, parent=application)
        track_model = TrackTableModel(application)
        album_model = AlbumListModel(track_model, application)
        artist_model = CollectionListModel(
            track_model,
            CollectionKind.ARTIST,
            application,
        )
        genre_model = CollectionListModel(
            track_model,
            CollectionKind.GENRE,
            application,
        )
        tv_show_model = CollectionListModel(
            track_model,
            CollectionKind.TV_SHOW,
            application,
        )
        music_video_model = CollectionListModel(
            track_model,
            CollectionKind.MUSIC_VIDEO_ALBUM,
            application,
        )
        device_coordinator = DeviceCoordinator(storage)
        device_controller = DeviceController(
            device_coordinator,
            track_model,
            settings,
            application,
        )
        artwork_controller = ArtworkController(device_coordinator, application)
        photo_controller = PhotoController(device_coordinator, application)
        backup_controller = BackupController(
            BackupService(device_coordinator),
            device_controller,
            settings,
            application,
        )
        cache_file = storage.host_cache_file(
            "iOpenPod",
            "host-media-library-v7.json",
        )
        host_media_controller = HostMediaScanController(
            HostMediaScanner(cache_file),
            application,
        )
        ipod_media_controller = IPodMediaScanController(
            device_coordinator,
            device_controller,
            application,
        )
        library_workspace = LibraryWorkspace(application)
        playback_backend = QtPlaybackBackend(device_coordinator, application)
        playback_controller = PlaybackController(
            playback_backend,
            application,
            workspace=library_workspace,
        )
        device_controller.ejectStarted.connect(playback_controller.clear_session)
        lyrics_controller = LyricsController(
            playback_controller, device_coordinator, library_workspace, application
        )
        synesthesia_controller = SynesthesiaController(
            WholeTrackMusicAnalyzer(),
            device_coordinator,
            application,
        )
        podcast_controller = PodcastController(
            device_coordinator,
            device_controller,
            application,
        )
        podcast_artwork_controller = PodcastArtworkController(
            HttpPodcastArtworkLoader(),
            application,
        )
        status = ApplicationStatus(application)
        library_write_controller = LibraryWriteController(
            device_coordinator,
            library_workspace,
            device_controller,
            settings,
            application,
        )
        device_controller.activeIPodChanged.connect(
            library_workspace.active_ipod_changed
        )
        device_controller.activeIPodChanged.connect(
            artwork_controller.active_ipod_changed
        )
        device_controller.activeIPodChanged.connect(
            photo_controller.active_ipod_changed
        )
        i18n_manager.languageChanged.connect(track_model.retranslate)
        i18n_manager.languageChanged.connect(album_model.retranslate)
        i18n_manager.languageChanged.connect(artist_model.retranslate)
        i18n_manager.languageChanged.connect(genre_model.retranslate)
        i18n_manager.languageChanged.connect(tv_show_model.retranslate)
        i18n_manager.languageChanged.connect(music_video_model.retranslate)
        i18n_manager.languageChanged.connect(
            playback_controller.queue_model.retranslate
        )
        i18n_manager.languageChanged.connect(
            playback_controller.history_model.retranslate
        )

        return cls(
            device_coordinator=device_coordinator,
            device_controller=device_controller,
            artwork_controller=artwork_controller,
            photo_controller=photo_controller,
            backup_controller=backup_controller,
            host_media_controller=host_media_controller,
            ipod_media_controller=ipod_media_controller,
            playback_controller=playback_controller,
            lyrics_controller=lyrics_controller,
            synesthesia_controller=synesthesia_controller,
            podcast_controller=podcast_controller,
            podcast_artwork_controller=podcast_artwork_controller,
            status=status,
            library_workspace=library_workspace,
            library_write_controller=library_write_controller,
            track_model=track_model,
            album_model=album_model,
            artist_model=artist_model,
            genre_model=genre_model,
            tv_show_model=tv_show_model,
            music_video_model=music_video_model,
            settings=settings,
            theme_manager=theme_manager,
            i18n_manager=i18n_manager,
        )

    def shutdown(self) -> None:
        """Flush persistent state and remove installed translators."""

        self.synesthesia_controller.shutdown()
        self.lyrics_controller.shutdown()
        self.playback_controller.shutdown()
        self.backup_controller.shutdown()
        self.host_media_controller.shutdown()
        self.ipod_media_controller.shutdown()
        self.podcast_controller.shutdown()
        self.podcast_artwork_controller.shutdown()
        self.library_write_controller.shutdown()
        self.artwork_controller.shutdown()
        self.photo_controller.shutdown()
        self.device_controller.shutdown()
        self.settings.sync()
        self.theme_manager.close()
        self.i18n_manager.close()
