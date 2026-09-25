"""Shared composition helpers for application-shell GUI tests."""

from PySide6.QtWidgets import QApplication
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.backup_controller import BackupController
from iOpenPod.app.backups import BackupService
from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
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
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController
from iOpenPod.app.podcasts.controller import PodcastController
from iOpenPod.app.podcasts.feed_client import HttpPodcastArtworkLoader
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.synesthesia import (
    SynesthesiaController,
    WholeTrackMusicAnalyzer,
)
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iPodDB.library import Track
from storage import Storage
from storage.testing import VirtualStoragePlatform


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def build_context(
    *,
    device_coordinator: DeviceCoordinator | None = None,
    playback_backend: FakePlaybackBackend | None = None,
) -> AppContext:
    """Compose an isolated GUI context without physical-device discovery."""

    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    track_model = TrackTableModel()
    album_model = AlbumListModel(track_model)
    artist_model = CollectionListModel(track_model, CollectionKind.ARTIST)
    genre_model = CollectionListModel(track_model, CollectionKind.GENRE)
    tv_show_model = CollectionListModel(track_model, CollectionKind.TV_SHOW)
    music_video_model = CollectionListModel(
        track_model,
        CollectionKind.MUSIC_VIDEO_ALBUM,
    )
    theme_manager = ThemeManager(APPLICATION, settings)
    i18n_manager = I18nManager(APPLICATION, settings)
    device_coordinator = device_coordinator or DeviceCoordinator(
        Storage(VirtualStoragePlatform()),
    )
    device_controller = DeviceController(
        device_coordinator,
        track_model,
        settings,
        APPLICATION,
    )
    artwork_controller = ArtworkController(device_coordinator, APPLICATION)
    photo_controller = PhotoController(device_coordinator, APPLICATION)
    backup_controller = BackupController(
        BackupService(device_coordinator),
        device_controller,
        settings,
        APPLICATION,
    )
    library_workspace = LibraryWorkspace()
    playback_controller = PlaybackController(
        playback_backend if playback_backend is not None else FakePlaybackBackend(),
        workspace=library_workspace,
    )
    podcast_controller = PodcastController(device_coordinator, device_controller)
    podcast_artwork_controller = PodcastArtworkController(HttpPodcastArtworkLoader())
    device_controller.activeIPodChanged.connect(library_workspace.active_ipod_changed)
    device_controller.activeIPodChanged.connect(artwork_controller.active_ipod_changed)
    device_controller.activeIPodChanged.connect(photo_controller.active_ipod_changed)
    translated_models = (
        track_model,
        album_model,
        artist_model,
        genre_model,
        tv_show_model,
        music_video_model,
        playback_controller.queue_model,
        playback_controller.history_model,
    )
    for model in translated_models:
        i18n_manager.languageChanged.connect(model.retranslate)
    return AppContext(
        device_coordinator=device_coordinator,
        device_controller=device_controller,
        artwork_controller=artwork_controller,
        photo_controller=photo_controller,
        backup_controller=backup_controller,
        host_media_controller=HostMediaScanController(HostMediaScanner()),
        ipod_media_controller=IPodMediaScanController(
            device_coordinator,
            device_controller,
        ),
        playback_controller=playback_controller,
        lyrics_controller=LyricsController(
            playback_controller, device_coordinator, library_workspace, APPLICATION
        ),
        synesthesia_controller=SynesthesiaController(
            WholeTrackMusicAnalyzer(enrichers=()),
            device_coordinator,
            APPLICATION,
        ),
        podcast_controller=podcast_controller,
        podcast_artwork_controller=podcast_artwork_controller,
        status=ApplicationStatus(APPLICATION),
        library_workspace=library_workspace,
        library_write_controller=LibraryWriteController(
            device_coordinator,
            library_workspace,
            device_controller,
            settings,
            APPLICATION,
        ),
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


def tracks(count: int) -> tuple[Track, ...]:
    """Build deterministic Track projections for shell and playback tests."""

    return tuple(
        Track(
            track_id=index,
            title=f"Track {index:05d}",
            artist=f"Artist {(index // 10) % 100:03d}",
            album=f"Album {index // 10:04d}",
            length_ms=180_000 + index,
            genre=f"Genre {(index // 10) % 12:02d}",
            year=1980 + ((index // 10) % 45),
            track_number=(index % 10) + 1,
            size_bytes=4_000_000 + index,
            bitrate_kbps=256,
            play_count=index % 50,
            rating=(index % 6) * 20,
        )
        for index in range(count)
    )


__all__ = ["APPLICATION", "build_context", "tracks"]
