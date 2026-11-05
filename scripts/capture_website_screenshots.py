"""Capture website/README screenshots from isolated real widgets and supplied art."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import PropertyMock, patch
from zoneinfo import ZoneInfo

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QStackedWidget, QTabWidget, QWidget
from scripts.capture_store_screenshots import (
    ROOT,
    artwork_provenance,
    child,
    host_artwork,
    navigate,
    sample_images,
    sample_ipod,
    sample_library,
    settle,
    show_sync,
)

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.backups.models import (
    BackupCatalog,
    BackupDeviceInfo,
    BackupInventory,
    SnapshotIdentityState,
    SnapshotInfo,
)
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_MODE,
    COLORFUL_MODE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    PLAYER_AUTO_MINIMIZE,
    IPodLibraryViewMode,
)
from iOpenPod.app.games_controller import GamesController
from iOpenPod.app.host_media_folders import HostMediaFolder, HostMediaType
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.app.services.game_catalog import catalog_games
from iOpenPod.app.services.game_library import GameCatalog
from iOpenPod.GUI.dialogs.media_folders import MediaFoldersDialog
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.library import (
    Playlist,
    PlaylistKind,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
)
from storage import HostPath


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork-dir", type=Path, required=True)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = "1"
    from tests.iOpenPod.GUI.application_shell_test_support import (
        APPLICATION,
        build_context,
    )

    output = ROOT / "website/screenshots/iop2"
    previews = ROOT / ".scratch/website-preview"
    previews.mkdir(parents=True, exist_ok=True)
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            raise RuntimeError(f"Cannot load Windows font {filename}")
    QFont.insertSubstitution("Sans Serif", "Segoe UI")
    APPLICATION.setFont(QFont("Segoe UI", 10))
    images = sample_images(args.artwork_dir)
    sources = host_artwork(images, previews / "artwork")
    context = build_context()
    context.artwork_controller.shutdown()
    context.photo_controller.shutdown()
    context = replace(
        context,
        artwork_controller=ArtworkController(images, APPLICATION),
        photo_controller=PhotoController(images, APPLICATION),
    )
    context.settings.set_global(APPEARANCE_MODE, "light")
    context.settings.set_global(COLORFUL_MODE, True)
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE,
        IPodLibraryViewMode.ITUNES_11.value,
    )
    library = sample_library()
    library = replace(
        library,
        playlists=(
            *library.playlists,
            replace(
                library.playlists[0],
                playlist_id=4,
                name="Phase",
                is_phase=True,
                description="A rhythm-game mix from the sample Library.",
            ),
        ),
    )
    active = sample_ipod(library)
    window = MainWindow(context, auto_discover=False)
    window.resize(1440, 960)
    context.library_workspace.load(
        library,
        photo_album_creation_type=active.profile.capabilities.artwork.photo_album_creation_type,
    )
    context.track_model.reset_tracks(library.tracks)
    child(window, Sidebar).set_active_ipod(active)
    child(window, CompactTopBar).set_active_ipod(active)
    context.status.show(
        "website-screenshot", "Sample library · Fictional media and supplied artwork"
    )
    window.show()
    manifest: list[dict[str, str | int]] = []

    def capture(widget: QWidget, name: str, caption: str) -> None:
        settle(APPLICATION)
        png = previews / f"{name}.png"
        if not widget.grab().save(str(png), "PNG"):
            raise RuntimeError(f"Cannot capture {name}")
        path = output / f"{name}.webp"
        with Image.open(png) as image:
            image.save(path, "WEBP", lossless=True, method=6)
            manifest.append(
                {
                    "file": path.name,
                    "caption": caption,
                    "width": image.width,
                    "height": image.height,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "capture_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                }
            )
        print(f"Captured {name}", flush=True)

    def main_pages() -> None:
        child(window, QStackedWidget, "workspaceStack").setCurrentIndex(0)

    try:
        navigate(window, PageId.ALBUMS)
        settle(APPLICATION)
        grid = child(child(window, LibraryPage, "albumsPage"), AlbumGridView)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(grid.model().index(0, 0)).center(),
        )
        # The isolated composition uses FakePlaybackBackend: render an active
        # Player without accessing audio files, hardware, or network services.
        context.settings.set_global(PLAYER_AUTO_MINIMIZE, False)
        context.playback_controller.play_now(library.tracks[:12])
        context.playback_controller.seek(67_000)
        settle(APPLICATION)
        assert context.playback_controller.playing
        assert child(window, PlayerBar).isVisible()
        capture(
            window,
            "album-library",
            "iOpenPod album library with matching sample artwork, the selected album track list, and a track playing in the Player",
        )

        context.playback_controller.clear_session()
        context.settings.set_global(PLAYER_AUTO_MINIMIZE, True)

        folders = MediaFoldersDialog(context.settings, window)
        folders.resize(900, 600)
        folders.add_folder(
            HostMediaFolder(
                HostPath(Path("C:/Sample Music")),
                media_types=frozenset({HostMediaType.AUDIO}),
            )
        )
        folders.show()
        capture(
            folders,
            "media-folders",
            "Choose Media Folders with per-folder media types and subfolder scanning",
        )
        folders.reject()

        show_sync(
            window,
            library,
            active,
            track_count=108,
            existing_track_count=12,
            artwork_sources=sources,
        )
        workspace = child(window, SyncWorkspace)
        workspace.selection.set_tracks_checked(
            tuple(t.track_id for t in library.tracks[36:72]), False
        )
        workspace.selection.set_tracks_checked(
            tuple(t.track_id for t in library.tracks[84:90]), False
        )
        window.resize(1440, 1150)
        workspace.show_selection()
        browser = workspace.browser
        assert browser is not None
        for _ in range(20):
            ready = [
                browser.artwork_provider.pixmap(i, LAYOUT.album_artwork_size, 1.0)
                is not None
                for i in range(1, 10)
            ]
            if all(ready):
                break
            settle(APPLICATION)
        else:
            raise RuntimeError("Sample Host artwork did not load")
        capture(
            window,
            "sync-media-selection",
            "Sync media selection with selected, mixed, and deselected sample albums",
        )
        window.resize(1440, 960)
        show_sync(window, library, active, track_count=24, artwork_sources=sources)
        workspace.selection.set_tracks_checked(
            tuple(t.track_id for t in library.tracks[12:24]), False
        )
        workspace.show_review()
        workspace.set_execution_available(True)
        capture(
            window,
            "sync-change-review",
            "Sync Review with selected sample additions and the Sync Selected action",
        )
        main_pages()
        navigate(window, PageId.SETTINGS)
        tabs = child(window, QTabWidget, "settingsTabs")
        tabs.setCurrentIndex(
            next(i for i in range(tabs.count()) if tabs.tabText(i) == "Transcoding")
        )
        capture(
            window,
            "audio-transcoding-settings",
            "Audio transcoding settings for encoder, bitrate, lossless conversion, and spoken-word media",
        )

        navigate(window, PageId.ALBUMS)
        provider = ArtworkPixmapProvider(context.artwork_controller, window)
        editor = MetadataEditorDialog(
            context.library_workspace,
            (library.tracks[0].track_id,),
            window,
            artwork_provider=provider,
        )
        editor.show()
        capture(
            editor,
            "track-metadata",
            "Edit Track with title, artist, album, genre, composer, and track metadata",
        )
        sections = child(editor, QListWidget, "metadataSectionNav")
        sections.setCurrentRow(
            next(
                i
                for i in range(sections.count())
                if sections.item(i).text() == "Artwork"
            )
        )
        capture(
            editor,
            "track-artwork",
            "Edit Track artwork with supplied cover art and controls to choose or clear artwork",
        )
        editor.reject()
        provider.shutdown()
        smart = Playlist(
            5,
            "Ambient favorites",
            kind=PlaylistKind.SMART,
            smart=SmartPlaylist(
                rules=SmartRuleGroup(
                    rules=(SmartRule(SmartField.GENRE, SmartOperator.IS, "Ambient"),)
                )
            ),
        )
        playlist_editor = PlaylistEditorDialog(PlaylistKind.SMART, smart, window)
        playlist_editor.show()
        capture(
            playlist_editor,
            "smart-playlist",
            "Smart Playlist editor with an Ambient genre rule",
        )
        playlist_editor.reject()

        navigate(window, PageId.PHOTOS)
        settle(APPLICATION)
        photo_grid = child(child(window, PhotoPage), PhotoGridView)
        QTest.mouseClick(
            photo_grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=photo_grid.visualRect(photo_grid.model().index(0, 0)).center(),
        )
        capture(
            window,
            "photo-albums",
            "Photo Library with supplied artwork, sample photo albums, and the selected photo inspector",
        )
        navigate(window, PageId.PLAYLISTS)
        playlist_tree = child(window, Sidebar).playlist_tree
        assert playlist_tree is not None
        playlist_tree.select_playlist(4)
        pages = child(window, QStackedWidget, "pageStack")
        assert isinstance(pages.currentWidget(), PlaylistPage)
        capture(
            window,
            "phase-playlist",
            "Phase Playlist with sample tracks, supplied artwork, and the Phase banner",
        )

        games = GameCatalog(catalog_games(active.profile))
        with (
            patch.object(
                GamesController,
                "catalog",
                new_callable=PropertyMock,
                return_value=games,
            ),
            patch.object(
                GamesController,
                "catalog_ready",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                GamesController,
                "active_ipod",
                new_callable=PropertyMock,
                return_value=active,
            ),
            patch.object(
                GamesController,
                "available",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(GamesController, "load_games"),
        ):
            context.games_controller.changed.emit()
            navigate(window, PageId.GAMES)
            capture(
                window,
                "click-wheel-games",
                "Games page with a sample installed-game inventory and the Install Games button",
            )

        device = BackupDeviceInfo(
            "sample-ipod",
            "Sample iPod",
            3,
            connected=True,
            identity_state=SnapshotIdentityState.NATIVE,
        )
        snapshots = tuple(
            SnapshotInfo(
                f"sample-{i}",
                f"2026-11-0{i}T14:00:00+00:00",
                device.device_id,
                device.device_name,
                file_count=312,
                total_size=1_600_000_000,
                note=note,
                identity_state=SnapshotIdentityState.NATIVE,
            )
            for i, note in (
                (4, "Before adding new albums"),
                (3, "Weekend library"),
                (1, "First library backup"),
            )
        )
        inventory = BackupInventory((device,), connected_device_id=device.device_id)
        catalog = BackupCatalog(device, snapshots, 1_650_000_000)
        backups = context.backup_controller

        def show_catalog(_device_id: str) -> None:
            backups.catalogChanged.emit(catalog)

        with (
            patch.object(
                backups,
                "refresh",
                side_effect=lambda: backups.inventoryChanged.emit(inventory),
            ),
            patch.object(
                backups,
                "load_catalog",
                side_effect=show_catalog,
            ),
        ):
            navigate(window, PageId.BACKUPS)
            capture(
                window,
                "backups",
                "Backups page with fictional Backup Snapshots for the sample iPod",
            )
        (output / "manifest.json").write_text(
            json.dumps(
                {
                    "captured_on": datetime.now(ZoneInfo("America/New_York"))
                    .date()
                    .isoformat(),
                    "source": "Real iOpenPod Qt widgets on Windows with fictional sample Library data and supplied GenericArt artwork. Game covers are bundled application assets.",
                    "appearance": "light",
                    "encoding": "Lossless WebP, method 6; complete widget captures at native dimensions",
                    "artwork": artwork_provenance(args.artwork_dir),
                    "screenshots": manifest,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        window.close()
        context.shutdown()
        APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    main()
