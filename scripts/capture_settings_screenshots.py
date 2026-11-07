"""Capture Settings examples from real widgets and the named GenericArt Library.

Run with ``uv run python -m scripts.capture_settings_screenshots --artwork-dir PATH``.
The isolated composition never opens physical devices or personal settings.
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
from PySide6.QtWidgets import QWidget
from scripts.capture_store_screenshots import (
    ROOT,
    artwork_provenance,
    child,
    navigate,
    sample_images,
    sample_ipod,
    sample_library,
    settle,
)

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_DARK_THEME,
    APPEARANCE_LIGHT_THEME,
    APPEARANCE_MODE,
    COLORFUL_MODE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    ITUNES_107_ARTWORK,
    NAVIGATION_STYLE,
    PLAYER_AUTO_MINIMIZE,
    PLAYER_POSITION,
    TRACK_TITLE_BAR_STYLE,
    DarkTheme,
    IPodLibraryViewMode,
    LightTheme,
    NavigationStyle,
    PlayerPosition,
    TrackTitleBarStyle,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.sidebar import Sidebar

OUTPUT = ROOT / "src/iOpenPod/assets/settings"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork-dir", type=Path, required=True)
    parser.add_argument(
        "--slate-only",
        action="store_true",
        help="Add Slate captures while preserving existing screenshots",
    )
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = "2"
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
    settings = context.settings
    settings.set_global(APPEARANCE_MODE, "light")
    settings.set_global(DRAFT_ALL_CHANGES, True)
    settings.set_global(NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value)
    settings.set_global(IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.SPLIT_TABLE.value)
    settings.set_global(PLAYER_AUTO_MINIMIZE, True)
    window = MainWindow(context, auto_discover=False)
    window.resize(1000, 680)
    library = sample_library()
    active = sample_ipod(library)
    context.library_workspace.load(library)
    context.track_model.reset_tracks(library.tracks)
    child(window, Sidebar).set_active_ipod(active)
    child(window, CompactTopBar).set_active_ipod(active)
    window.show()
    captured: list[dict[str, str | int]] = []
    if args.slate_only:
        manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        captured = [
            item
            for item in manifest["screenshots"]
            if not item["file"].startswith("slate/")
        ]
    capture_prefix = ""

    def capture(widget: QWidget, filename: str, *, height: int | None = None) -> None:
        settle(APPLICATION)
        surface = widget.window()
        rect = QRect(widget.mapTo(surface, QPoint()), widget.size())
        if height is not None:
            rect.setHeight(min(height, rect.height()))
        image = surface.grab(rect)
        filename = capture_prefix + filename
        path = OUTPUT / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(path), "PNG"):
            raise RuntimeError(f"Cannot capture {filename}")
        captured.append(
            {
                "file": filename,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "width": image.width(),
                "height": image.height(),
                "device_pixel_ratio": 2,
            }
        )
        print(f"Captured {filename}", flush=True)

    def select_album() -> LibraryPage:
        navigate(window, PageId.ALBUMS)
        settle(APPLICATION)
        page = child(window, LibraryPage, "albumsPage")
        grid = child(page, AlbumGridView)
        index = grid.model().index(0, 0)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        settle(APPLICATION)
        return page

    try:
        if not args.slate_only:
            page = select_album()
            for theme in (*LightTheme, *DarkTheme):
                if isinstance(theme, LightTheme):
                    settings.set_global(APPEARANCE_LIGHT_THEME, theme.value)
                    settings.set_global(APPEARANCE_MODE, "light")
                else:
                    settings.set_global(APPEARANCE_DARK_THEME, theme.value)
                    settings.set_global(APPEARANCE_MODE, "dark")
                capture(page, f"theme-{theme.value}.png")
        settings.set_global(APPEARANCE_LIGHT_THEME, LightTheme.PORCELAIN.value)
        settings.set_global(APPEARANCE_DARK_THEME, DarkTheme.SLATE.value)
        for appearance in ("dark",) if args.slate_only else ("light", "dark"):
            capture_prefix = "slate/" if appearance == "dark" else ""
            settings.set_global(APPEARANCE_MODE, appearance)
            settings.set_global(NAVIGATION_STYLE, NavigationStyle.COMPACT_TOP_BAR.value)
            settings.set_global(TRACK_TITLE_BAR_STYLE, TrackTitleBarStyle.FLAT.value)
            page = select_album()
            for colorful in (False, True):
                settings.set_global(COLORFUL_MODE, colorful)
                capture(page, f"colorful-{'on' if colorful else 'off'}.png")
            settings.set_global(COLORFUL_MODE, False)
            for titlebar in TrackTitleBarStyle:
                settings.set_global(TRACK_TITLE_BAR_STYLE, titlebar.value)
                capture(page, f"titlebar-{titlebar.value}.png")
            settings.set_global(TRACK_TITLE_BAR_STYLE, TrackTitleBarStyle.FLAT.value)

            for mode, name in (
                (IPodLibraryViewMode.SPLIT_TABLE, "split"),
                (IPodLibraryViewMode.WHOLE_PAGE_TABLE, "whole"),
                (IPodLibraryViewMode.ITUNES_11, "inline"),
            ):
                settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
                page = select_album()
                capture(page, f"library-{name}.png")
            settings.set_global(
                IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.SPLIT_TABLE.value
            )
            page = select_album()

            for navigation, name in (
                (NavigationStyle.SIDEBAR, "sidebar"),
                (NavigationStyle.COMPACT_TOP_BAR, "compact"),
            ):
                settings.set_global(NAVIGATION_STYLE, navigation.value)
                capture(window, f"navigation-{name}.png")

            # FakePlaybackBackend supplies Player state without opening audio files.
            context.playback_controller.play_now(library.tracks[:12])
            context.playback_controller.seek(67_000)
            for position in PlayerPosition:
                settings.set_global(PLAYER_POSITION, position.value)
                capture(window, f"player-{position.value}.png")
            settings.set_global(PLAYER_POSITION, PlayerPosition.TOP.value)
            context.playback_controller.clear_session()
            for minimize, name in ((False, "visible"), (True, "hidden")):
                settings.set_global(PLAYER_AUTO_MINIMIZE, minimize)
                capture(window, f"idle-{name}.png")

            summary = child(window, DeviceSummaryPage)
            summary.set_active_ipod(active)
            navigate(window, PageId.DEVICE_SUMMARY)
            for classic, name in ((False, "standard"), (True, "classic")):
                settings.set_global(ITUNES_107_ARTWORK, classic)
                capture(summary, f"device-{name}.png")

        (OUTPUT / "manifest.json").write_text(
            json.dumps(
                {
                    "source": "Actual iOpenPod Qt widgets, with the established GenericArt filename-to-Album mapping from scripts/screenshot_catalog.py.",
                    "artwork": artwork_provenance(args.artwork_dir),
                    "screenshots": captured,
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
