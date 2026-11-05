"""Capture the onboarding illustrations from real Qt widgets and fictional data.

Run ``uv run python -m scripts.capture_onboarding_screenshots``. Uses the existing
isolated screenshot fixtures; never opens physical devices or personal settings.
"""

import argparse
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStackedWidget, QTabWidget, QWidget
from scripts.capture_store_screenshots import (
    artwork_provenance,
    child,
    navigate,
    sample_images,
    sample_ipod,
    sample_library,
    settle,
    show_sync,
)

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_MODE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    ITUNES_107_ARTWORK,
    NAVIGATION_STYLE,
    IPodLibraryViewMode,
    NavigationStyle,
)
from iOpenPod.app.host_media_folders import HostMediaFolder, HostMediaType
from iOpenPod.app.host_media_library import HostArtworkKind, HostMediaArtworkSource
from iOpenPod.GUI.dialogs.media_folders import MediaFoldersDialog
from iOpenPod.GUI.dialogs.onboarding import OnboardingDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from storage import HostPath

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/iOpenPod/assets/onboarding"


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

    OUTPUT.mkdir(parents=True, exist_ok=True)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        if QFontDatabase.addApplicationFont(str(fonts / filename)) < 0:
            raise RuntimeError(f"Cannot load Windows font {filename}")
    QFont.insertSubstitution("Sans Serif", "Segoe UI")
    APPLICATION.setFont(QFont("Segoe UI", 10))
    context = build_context()
    context.artwork_controller.shutdown()
    images = sample_images(args.artwork_dir)
    context = replace(
        context, artwork_controller=ArtworkController(images, APPLICATION)
    )
    context.settings.set_global(APPEARANCE_MODE, "light")
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    window = MainWindow(context, auto_discover=False)
    window.resize(1200, 740)
    window.show()

    def capture(
        widget: QWidget,
        name: str,
        directory: Path = OUTPUT,
        *,
        height: int | None = None,
        width: int | None = None,
    ) -> None:
        settle(APPLICATION)
        # Capture from the actual window so transparent child widgets retain the
        # background behind them, including when the illustration is shown dark.
        surface = widget.window()
        rectangle = QRect(widget.mapTo(surface, QPoint()), widget.size())
        if height is not None:
            rectangle.setHeight(min(height, rectangle.height()))
        if width is not None:
            rectangle.setWidth(min(width, rectangle.width()))
        if not surface.grab(rectangle).save(str(directory / name), "PNG"):
            raise RuntimeError(f"Could not capture {name}")
        print(f"Captured {name}", flush=True)

    try:
        library = sample_library()
        active = sample_ipod(library)
        context.library_workspace.load(library)
        context.track_model.reset_tracks(library.tracks)
        child(window, Sidebar).set_active_ipod(active)
        child(window, CompactTopBar).set_active_ipod(active)
        navigate(window, PageId.ALBUMS)
        for mode, name in (
            (NavigationStyle.SIDEBAR, "sidebar"),
            (NavigationStyle.COMPACT_TOP_BAR, "compact"),
        ):
            context.settings.set_global(NAVIGATION_STYLE, mode.value)
            if mode is NavigationStyle.COMPACT_TOP_BAR:
                # Capture at the supported minimum width so the complete bar is
                # legible in the tour. Keep the Albums heading and upper artwork
                # row as context, without the rest of the Library dominating.
                window.resize(960, 740)
                capture(window, f"navigation-{name}.png", height=240)
                window.resize(1200, 740)
            else:
                capture(window, f"navigation-{name}.png")
            button_name = (
                "compactSyncWithHost"
                if mode is NavigationStyle.COMPACT_TOP_BAR
                else "syncWithHost"
            )
            sync_button = child(window, ActionButton, button_name)
            sync_button.setFocus()
            sync_button.setDown(True)
            # Show the real pressed control, without dispatching a Sync action.
            capture(window, f"sync-start-{name}.png", width=600, height=320)
            sync_button.setDown(False)
        context.settings.set_global(
            NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value
        )
        page = child(window, LibraryPage, "albumsPage")
        for library_mode, name in (
            (IPodLibraryViewMode.SPLIT_TABLE, "split"),
            (IPodLibraryViewMode.WHOLE_PAGE_TABLE, "whole"),
            (IPodLibraryViewMode.ITUNES_11, "inline"),
        ):
            context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, library_mode.value)
            settle(APPLICATION)
            grid = child(page, AlbumGridView)
            index = grid.model().index(0, 0)
            QTest.mouseClick(
                grid.viewport(),
                Qt.MouseButton.LeftButton,
                pos=grid.visualRect(index).center(),
            )
            capture(page, f"library-{name}.png")
        summary = child(window, DeviceSummaryPage)
        summary.set_active_ipod(active)
        navigate(window, PageId.DEVICE_SUMMARY)
        for classic, name in ((False, "standard"), (True, "classic")):
            context.settings.set_global(ITUNES_107_ARTWORK, classic)
            capture(summary, f"device-{name}.png")
        navigate(window, PageId.SETTINGS)
        window.resize(960, 740)
        tabs = child(window, QTabWidget, "settingsTabs")
        tabs.setCurrentIndex(
            next(i for i in range(tabs.count()) if tabs.tabText(i) == "Transcoding")
        )
        capture(child(window, SettingsPage), "transcoding.png", height=380)
        window.resize(1200, 740)

        folders = MediaFoldersDialog(context.settings, window)
        folders.resize(680, 460)
        folders.add_folder(
            HostMediaFolder(
                HostPath(Path("C:/Sample Music")),
                media_types=frozenset({HostMediaType.AUDIO}),
            )
        )
        folders.show()
        capture(folders, "sync-folders.png")
        folders.reject()

        # The Host browser owns its own artwork loader, so provide real fixture
        # image sources instead of relying on the device's SampleImages loader.
        artwork_directory = ROOT / ".scratch/onboarding-preview/artwork"
        artwork_directory.mkdir(parents=True, exist_ok=True)
        artwork_sources: list[HostMediaArtworkSource] = []
        for artwork_id, cover in images.covers.items():
            path = artwork_directory / f"{artwork_id}.png"
            cover.save(path)
            facts = path.stat()
            artwork_sources.append(
                HostMediaArtworkSource(
                    artwork_id,
                    HostArtworkKind.FOLDER,
                    HostPath(path),
                    facts.st_size,
                    facts.st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        window.resize(960, 900)
        # Show three Albums in each group, including one already on the iPod.
        show_sync(
            window,
            library,
            active,
            track_count=72,
            existing_track_count=12,
            artwork_sources=tuple(artwork_sources),
        )
        workspace = child(window, SyncWorkspace)
        workspace.selection.set_tracks_checked(
            tuple(track.track_id for track in library.tracks[36:72]), False
        )
        workspace.show_selection()
        browser = workspace.browser
        assert browser is not None
        for _ in range(10):
            ready = [
                browser.artwork_provider.pixmap(
                    artwork_id, LAYOUT.album_artwork_size, 1.0
                )
                is not None
                for artwork_id in range(1, 7)
            ]
            if all(ready):
                break
            settle(APPLICATION)
        else:
            raise RuntimeError("Sample Album artwork did not load")
        capture(workspace, "sync-selection.png")
        # Keep the Review illustration focused on the original small proposal.
        window.resize(960, 620)
        show_sync(
            window,
            library,
            active,
            track_count=24,
            artwork_sources=tuple(artwork_sources),
        )
        workspace.selection.set_tracks_checked(
            tuple(track.track_id for track in library.tracks[12:24]), False
        )
        workspace.show_review()
        # This is a simulated ready-to-sync state; no execution action is sent.
        workspace.set_execution_available(True)
        capture(workspace, "sync-review.png")

        (OUTPUT / "manifest.json").write_text(
            json.dumps(
                {
                    "source": "Real Qt widgets with fictional Library data and supplied GenericArt artwork.",
                    "artwork": artwork_provenance(args.artwork_dir),
                    "screenshots": [
                        {
                            "file": path.name,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for path in sorted(OUTPUT.glob("*.png"))
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        # Review artifacts stay private; only the reusable illustrations ship.
        previews = ROOT / ".scratch/onboarding-preview"
        previews.mkdir(parents=True, exist_ok=True)
        for appearance in ("light", "dark"):
            context.settings.set_global(APPEARANCE_MODE, appearance)
            dialog = OnboardingDialog(context.settings, context.i18n_manager, window)
            dialog.show()
            normal_size = dialog.size()
            page_count = child(dialog, QStackedWidget, "onboardingPages").count()
            for page_index in range(page_count):
                capture(dialog, f"{appearance}-{page_index + 1}.png", previews)
                dialog.resize(560, 440)
                capture(dialog, f"{appearance}-{page_index + 1}-small.png", previews)
                dialog.resize(normal_size)
                if page_index < page_count - 1:
                    child(dialog, ActionButton, "onboardingNext").click()
            dialog.reject()
    finally:
        window.close()
        context.shutdown()
        APPLICATION.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    main()
