"""Track title-bar appearance switches without replacing live Library controls."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
    tracks,
)

from iOpenPod.app.core.settings.definitions import (
    TRACK_TITLE_BAR_STYLE,
    AppearanceMode,
    DarkTheme,
    TrackTitleBarStyle,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.track_list_header import LibrarySplitter
from iOpenPod.GUI.widgets.track_table import TrackTable


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
def test_round_title_bar_switches_live_and_preserves_interaction(
    mode: AppearanceMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    context.track_model.replace_tracks(tracks(100))
    context.theme_manager.set_mode(mode)
    window = MainWindow(context, auto_discover=False)
    try:
        window.resize(1100, 760)
        window.show()
        APPLICATION.processEvents()
        splitter = window.findChild(LibrarySplitter, "librarySplitter")
        combo = window.findChild(AppComboBox, "trackTitleBarStyleCombo")
        table = window.findChild(TrackTable, "trackTable")
        assert splitter is not None and combo is not None and table is not None
        header = splitter.track_header
        search = header.findChild(SearchField)
        assert search is not None
        assert [combo.itemText(i) for i in range(combo.count())] == ["Flat", "Round"]
        assert combo.currentData() == "flat"
        header.set_query("kept search")
        sizes = splitter.sizes()
        columns = table.horizontalHeader().saveState()
        flat = header.grab().toImage()

        combo.setCurrentIndex(combo.findData("round"))
        APPLICATION.processEvents()
        assert context.settings.get(TRACK_TITLE_BAR_STYLE) == "round"
        assert search.property("roundTitleBar") is True
        assert search.text() == "kept search"
        assert splitter.sizes() == sizes
        assert table.horizontalHeader().saveState() == columns
        rounded = header.grab().toImage()
        assert rounded != flat
        assert rounded.pixelColor(0, 0) == QColor(context.theme_manager.tokens.surface)
        # Empty space between title and search exposes the vertical gradient.
        center = rounded.width() // 2
        assert rounded.pixelColor(center, 5) != rounded.pixelColor(
            center, rounded.height() - 5
        )

        provider = window.findChild(ArtworkPixmapProvider)
        assert provider is not None

        def dominant_color(
            _artwork_id: int, _logical_size: int, _device_pixel_ratio: float
        ) -> tuple[int, int, int]:
            return (216, 24, 80)

        monkeypatch.setattr(provider, "dominant_color", dominant_color)
        header.set_context("Album", 64)
        context.theme_manager.set_colorful_mode(True)
        tinted = header.grab().toImage()
        assert tinted.pixelColor(center, 5) != rounded.pixelColor(center, 5)
        assert tinted.pixelColor(0, 0) == rounded.pixelColor(0, 0)

        origin = QPoint(4, header.height() // 2)
        QTest.mousePress(header, Qt.MouseButton.LeftButton, pos=origin)
        QTest.mouseMove(header, origin + QPoint(0, 36), delay=10)
        QTest.mouseRelease(
            header, Qt.MouseButton.LeftButton, pos=origin + QPoint(0, 36)
        )
        APPLICATION.processEvents()
        assert splitter.sizes() != sizes

        context.settings.reset_global(TRACK_TITLE_BAR_STYLE)
        assert combo.currentData() == "flat"
        assert search.property("roundTitleBar") is False
        assert search.text() == "kept search"
    finally:
        window.close()
        context.shutdown()


def test_saved_round_title_bar_applies_to_new_headers_and_survives_theme_changes() -> (
    None
):
    context = build_context()
    context.settings.set_global(TRACK_TITLE_BAR_STYLE, TrackTitleBarStyle.ROUND.value)
    window = MainWindow(context, auto_discover=False)
    try:
        headers = window.findChildren(LibrarySplitter)
        assert headers
        for splitter in headers:
            search = splitter.track_header.findChild(SearchField)
            assert search is not None and search.property("roundTitleBar") is True
        context.theme_manager.set_mode(AppearanceMode.DARK)
        context.theme_manager.set_dark_theme(DarkTheme.ORIGINAL)
        page = window.findChild(SettingsPage)
        combo = window.findChild(AppComboBox, "trackTitleBarStyleCombo")
        assert page is not None and combo is not None
        page.retranslate_ui()
        assert combo.currentData() == "round"
        assert context.theme_manager.track_title_bar_style is TrackTitleBarStyle.ROUND
        for splitter in headers:
            search = splitter.track_header.findChild(SearchField)
            assert search is not None and search.property("roundTitleBar") is True
    finally:
        window.close()
        context.shutdown()
