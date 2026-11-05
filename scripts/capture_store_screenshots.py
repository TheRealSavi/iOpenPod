"""Capture real application widgets with an isolated, deterministic sample library.

Run with ``uv run python -m scripts.capture_store_screenshots`` on Windows.
No physical devices, existing settings, network, or private media are accessed.
Supply --artwork-dir with the user-provided GenericArt folder for every capture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QTabWidget, QWidget

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_MODE,
    COLORFUL_MODE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    AppearanceMode,
    IPodLibraryViewMode,
)
from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.photos import PhotoImage, PhotoRequest
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMetadata,
)
from storage import FileFingerprint, HostPath

ROOT = Path(__file__).resolve().parents[1]
ALBUMS = (
    ("Amber Horizon", "The Sample Ensemble", "Ambient", "#fbc278", "#78415c"),
    ("Blue Hour", "The Sample Ensemble", "Electronic", "#64d5de", "#203461"),
    ("Coastal Lines", "Studio Example", "Instrumental", "#bce1d3", "#266675"),
    ("Daylight Studies", "Studio Example", "Electronic", "#f3db77", "#dd8362"),
    ("Echo Garden", "Demo Collective", "Ambient", "#adbd81", "#294d54"),
    ("Faraway Forms", "Demo Collective", "Instrumental", "#eabdce", "#634991"),
    ("Golden Islands", "The Sample Ensemble", "Jazz", "#edd9a1", "#ac743b"),
    ("Harbor Lights", "Studio Example", "Electronic", "#9bcece", "#304e70"),
    ("Into the Quiet", "Demo Collective", "Ambient", "#f0c5a1", "#675078"),
    ("Juniper Morning", "The Sample Ensemble", "Instrumental", "#c4d9a4", "#466b57"),
    ("Kinetic Shapes", "Studio Example", "Electronic", "#efbd92", "#b75d58"),
    ("Late Summer", "Demo Collective", "Jazz", "#f2cd87", "#5c8b86"),
    ("Moonlit Geometry", "The Sample Ensemble", "Ambient", "#bdc1e5", "#53568a"),
    ("Northern Current", "Studio Example", "Electronic", "#9ed7ca", "#2b767f"),
    ("Open Windows", "Demo Collective", "Instrumental", "#e8ccaf", "#8a6467"),
    ("Paper Planets", "The Sample Ensemble", "Electronic", "#d5bcdf", "#885e93"),
    ("Quiet Architecture", "Studio Example", "Ambient", "#b7d1df", "#496883"),
    ("River Patterns", "Demo Collective", "Instrumental", "#bed6ad", "#5b7b72"),
    ("Soft Signals", "The Sample Ensemble", "Electronic", "#ebb3ab", "#aa6381"),
    ("Tidal Sketches", "Studio Example", "Jazz", "#b7dfe3", "#5c87ab"),
    ("Under the Canopy", "Demo Collective", "Ambient", "#c5d8af", "#577864"),
    ("Velvet Orbit", "The Sample Ensemble", "Electronic", "#d9b2cd", "#755774"),
    ("Wildflower Maps", "Studio Example", "Instrumental", "#e5cb9e", "#a77964"),
    ("Yesterday's Colors", "Demo Collective", "Jazz", "#bfcfe2", "#638b93"),
)
TITLES = (
    "First Light",
    "A Place to Begin",
    "Open Water",
    "Slow Motion",
    "In the Distance",
    "Between the Lines",
    "Small Discoveries",
    "Parallel Paths",
    "Still Moving",
    "The Long Way Home",
    "After the Rain",
    "Until Tomorrow",
)


def sample_images(directory: Path) -> SampleImages:
    """Decode supplied artwork without modifying the source files."""
    files = sorted(
        (path for path in directory.iterdir() if path.suffix.lower() == ".png"),
        key=lambda path: path.name.casefold(),
    )
    if len(files) < len(ALBUMS):
        raise ValueError(f"Expected at least {len(ALBUMS)} PNG artworks in {directory}")
    decoded: list[Image.Image] = []
    for path in files:
        with Image.open(path) as source:
            decoded.append(ImageOps.contain(source.convert("RGB"), (720, 720)))
    return SampleImages(
        dict(enumerate(decoded[: len(ALBUMS)], 1)),
        dict(enumerate(decoded[-12:], 1)),
    )


def artwork_provenance(directory: Path) -> list[dict[str, str]]:
    return [
        {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(
            directory.glob("*.png"), key=lambda path: path.name.casefold()
        )
    ]


def host_artwork(
    images: SampleImages, directory: Path
) -> tuple[HostMediaArtworkSource, ...]:
    """Provide actual fixture files to the Host browser's independent image loader."""
    directory.mkdir(parents=True, exist_ok=True)
    sources: list[HostMediaArtworkSource] = []
    for artwork_id, cover in images.covers.items():
        path = directory / f"{artwork_id}.png"
        cover.save(path)
        facts = path.stat()
        sources.append(
            HostMediaArtworkSource(
                artwork_id,
                HostArtworkKind.FOLDER,
                HostPath(path),
                facts.st_size,
                facts.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return tuple(sources)


@dataclass
class SampleImages:
    covers: dict[int, Image.Image]
    photos: dict[int, Image.Image]

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        source = self.covers.get(request.artwork_id)
        if source is None:
            return None
        return ArtworkImage(
            f"sample-cover-{request.artwork_id}",
            request.artwork_id,
            1,
            source.width,
            source.height,
            source.tobytes(),
        )

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None:
        source = self.photos.get(request.photo_id)
        if source is None:
            return None
        return PhotoImage(
            f"sample-photo-{request.photo_id}",
            request.photo_id,
            request.format_id or 1067,
            source.width,
            source.height,
            source.tobytes(),
        )


def sample_library() -> LibrarySnapshot:
    tracks = tuple(
        Track(
            track_id=album_id * 100 + number,
            title=title,
            artist=artist,
            album=album,
            length_ms=(169 + number * 9 + album_id * 3) * 1000,
            genre=genre,
            year=2026,
            track_number=number,
            size_bytes=5_000_000 + number * 70_000,
            bitrate_kbps=256,
            play_count=(album_id + number) % 15,
            rating=80 if number % 3 else 100,
            artwork_id=album_id,
            metadata=TrackMetadata(
                file_format="AAC audio",
                total_tracks=12,
                sample_rate_hz=44100,
                comment="Fictional sample metadata for iOpenPod Store screenshots.",
            ),
        )
        for album_id, (album, artist, genre, _, _) in enumerate(ALBUMS, 1)
        for number, title in enumerate(TITLES, 1)
    )
    playlists = tuple(
        Playlist(
            playlist_id=index,
            name=name,
            entries=tuple(
                PlaylistEntry(f"sample-{index}-{track.track_id}", track.track_id)
                for track in tracks[index - 1 :: 7][:24]
            ),
            description="A hand-picked mix from the fictional sample library.",
        )
        for index, name in enumerate(
            ("Weekend Wandering", "Focus & Flow", "Evening Unwind"), 1
        )
    )
    photos = tuple(
        Photo(
            photo_id=index,
            rating=80,
            taken_date=1780358400 + index * 86400,
            source_size_bytes=320000,
            representations=(
                PhotoRepresentation(
                    PhotoRepresentationKind.THUMBNAIL,
                    1067,
                    "Photos/Thumbs/F1067_1.ithmb",
                    (index - 1) * 518400,
                    518400,
                    720,
                    480,
                ),
            ),
        )
        for index in range(1, 13)
    )
    return LibrarySnapshot(
        tracks,
        playlists,
        "Sample iPod",
        PhotoLibrary(
            photos, (PhotoAlbum(1, "Landscape Studies", tuple(range(1, 13))),)
        ),
    )


def sample_ipod(library: LibrarySnapshot) -> ActiveIPod:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB029")
    if profile is None:
        raise RuntimeError("Expected iPod Classic profile MB029")
    candidate = DeviceCandidate(
        DeviceCandidateId("store-screenshot-sample"),
        "Sample iPod",
        "Synthetic sample, no attached device",
        "USB",
        IdentificationStatus.EXACT,
        DeviceReadiness.READY,
        profile,
        80_000_000_000,
        77_600_000_000,
    )
    return ActiveIPod(
        candidate,
        profile,
        library,
        "iTunesDB",
        FileFingerprint(380000, 0, 0, 0, "0" * 64),
    )


def child[T: QWidget](window: QWidget, kind: type[T], name: str = "") -> T:
    result = window.findChild(kind, name) if name else window.findChild(kind)
    if result is None:
        raise RuntimeError(f"Missing capture widget: {kind.__name__} {name}")
    return result


def settle(application: QApplication) -> None:
    for _ in range(8):
        application.processEvents()
        QTest.qWait(60)


def navigate(window: MainWindow, page: PageId) -> None:
    sidebar = child(window, Sidebar)
    sidebar.pageRequested.emit(page.value)


def show_sync(
    window: MainWindow,
    library: LibrarySnapshot,
    active: ActiveIPod,
    *,
    track_count: int = 12,
    existing_track_count: int = 0,
    artwork_sources: tuple[HostMediaArtworkSource, ...] = (),
) -> None:
    host_tracks = tuple(
        replace(
            track,
            metadata=replace(
                track.metadata,
                location=f"C:/Sample Music/{track.album}/{track.title}.m4a",
            ),
        )
        for track in library.tracks[:track_count]
    )
    host = HostMediaLibrary(
        LibrarySnapshot(host_tracks),
        tuple(
            HostMediaSource(
                HostPath(Path(track.metadata.location)),
                HostMediaFileKind.AUDIO,
                track.size_bytes,
                0,
            )
            for track in host_tracks
        ),
        (),
        HostMediaCacheStats(),
        artwork_sources=artwork_sources,
    )
    items = tuple(
        SyncPlanItem(
            SyncPlanAction.UNCHANGED
            if index < existing_track_count
            else SyncPlanAction.ADD,
            SyncPlanMediaKind.TRACK,
            SyncPlanBasis.TRACK_DETAILS_MATCH
            if index < existing_track_count
            else SyncPlanBasis.HOST_ONLY,
            track.title,
            f"{track.artist} · {track.album}",
            track.metadata.location,
            ipod_id=track.track_id if index < existing_track_count else None,
        )
        for index, track in enumerate(host_tracks)
    )
    workspace = child(window, SyncWorkspace)
    workspace.load_comparison(
        host,
        SyncPlan(items),
        active,
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
    )
    workspace.selection.set_tracks_checked(
        tuple(track.track_id for track in host_tracks), True
    )
    workspace.show_review()
    child(window, QStackedWidget, "workspaceStack").setCurrentWidget(workspace)
    child(workspace, ActionButton, "syncReviewExpandAll").click()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "packaging/windows/store/screenshots"
    )
    parser.add_argument("--artwork-dir", type=Path, required=True)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = "1"
    # Import after configuring the offscreen platform: this isolated helper owns
    # its QApplication and uses VirtualStoragePlatform and in-memory settings.
    from tests.iOpenPod.GUI.application_shell_test_support import (
        APPLICATION,
        build_context,
    )

    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in (
        "segoeui.ttf",
        "segoeuib.ttf",
        "seguisym.ttf",
        "seguiemj.ttf",
        "arial.ttf",
        "arialbd.ttf",
    ):
        if QFontDatabase.addApplicationFont(str(fonts / filename)) < 0:
            raise RuntimeError(f"Cannot load Windows font {filename}")
    QFont.insertSubstitution("Sans Serif", "Segoe UI")
    APPLICATION.setFont(QFont("Segoe UI", 10))
    context = build_context()
    images = sample_images(args.artwork_dir)
    artwork_sources = host_artwork(images, ROOT / ".scratch/store-preview/artwork")
    context.artwork_controller.shutdown()
    context.photo_controller.shutdown()
    context = replace(
        context,
        artwork_controller=ArtworkController(images, APPLICATION),
        photo_controller=PhotoController(images, APPLICATION),
    )
    context.settings.set_global(APPEARANCE_MODE, AppearanceMode.DARK.value)
    context.settings.set_global(COLORFUL_MODE, True)
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    library = sample_library()
    active = sample_ipod(library)
    window = MainWindow(context, auto_discover=False)
    window.resize(1920, 1080)
    context.library_workspace.load(
        library,
        photo_album_creation_type=active.profile.capabilities.artwork.photo_album_creation_type,
    )
    context.track_model.reset_tracks(library.tracks)
    child(window, Sidebar).set_active_ipod(active)
    child(window, CompactTopBar).set_active_ipod(active)
    navigate(window, PageId.ALBUMS)
    context.status.show(
        "store-screenshot",
        "Sample library · Fictional media and supplied artwork",
    )
    window.show()
    manifest: list[dict[str, str | int]] = []

    def capture(name: str, caption: str) -> None:
        settle(APPLICATION)
        path = output / name
        pixmap = window.grab()
        if (pixmap.width(), pixmap.height()) != (1920, 1080):
            raise RuntimeError(f"Unexpected capture size {pixmap.size()}")
        if not pixmap.save(str(path), "PNG"):
            raise RuntimeError(f"Could not save {path}")
        manifest.append(
            {
                "file": name,
                "caption": caption,
                "width": 1920,
                "height": 1080,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    try:
        capture(
            "01-album-library.png",
            "Browse your iPod music by album, artist, genre, or track. Shown with a fictional sample library.",
        )
        grid = child(
            child(
                child(window, QStackedWidget, "pageStack"), LibraryPage, "albumsPage"
            ),
            AlbumGridView,
        )
        index = grid.model().index(0, 0)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        capture(
            "02-album-details.png",
            "Open an album to browse its tracks, metadata, ratings, and artwork.",
        )
        navigate(window, PageId.PLAYLISTS)
        playlist_tree = child(window, Sidebar).playlist_tree
        assert playlist_tree is not None
        playlist_tree.select_playlist(1)
        pages = child(window, QStackedWidget, "pageStack")
        assert isinstance(pages.currentWidget(), PlaylistPage)
        capture(
            "03-playlists.png",
            "Browse and organize playlists with track details and a cover-art overview.",
        )
        navigate(window, PageId.PHOTOS)
        settle(APPLICATION)
        photo_grid = child(child(window, PhotoPage), PhotoGridView)
        photo_index = photo_grid.model().index(0, 0)
        QTest.mouseClick(
            photo_grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=photo_grid.visualRect(photo_index).center(),
        )
        capture(
            "04-photo-library.png",
            "Browse photo albums and inspect the image representations stored on a supported iPod. Sample illustrations shown.",
        )
        show_sync(window, library, active, artwork_sources=artwork_sources)
        capture(
            "05-sync-review.png",
            "Review selected changes before syncing media from your computer to your iPod. No changes are applied in this sample.",
        )
        show_sync(
            window,
            library,
            active,
            track_count=len(library.tracks),
            artwork_sources=artwork_sources,
        )
        workspace = child(window, SyncWorkspace)
        workspace.show_selection()
        browser = workspace.browser
        assert browser is not None
        for _ in range(20):
            ready = [
                browser.artwork_provider.pixmap(i, LAYOUT.album_artwork_size, 1.0)
                is not None
                for i in images.covers
            ]
            if all(ready):
                break
            settle(APPLICATION)
        else:
            raise RuntimeError("Sample Host artwork did not load")
        capture(
            "07-sync-selection.png",
            "Select media from a fictional Host library before reviewing the Sync Plan.",
        )
        child(window, QStackedWidget, "workspaceStack").setCurrentIndex(0)
        navigate(window, PageId.SETTINGS)
        tabs = child(window, QTabWidget, "settingsTabs")
        tabs.setCurrentIndex(
            next(i for i in range(tabs.count()) if tabs.tabText(i) == "About")
        )
        capture(
            "06-about-and-credits.png",
            "Free and open source, with optional donations and acknowledgements for the projects that make iOpenPod possible.",
        )
        tabs.setCurrentIndex(
            next(i for i in range(tabs.count()) if tabs.tabText(i) == "Transcoding")
        )
        capture(
            "08-transcoding-settings.png",
            "Choose audio and video conversion settings in the real iOpenPod Settings page.",
        )
        (output / "manifest.json").write_text(
            json.dumps(
                {
                    "resolution": "1920x1080",
                    "artwork": artwork_provenance(args.artwork_dir),
                    "source": "Unmodified iOpenPod application widgets rendered by Qt on Windows with deterministic synthetic data.",
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
    print(f"Captured {len(manifest)} screenshots in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
