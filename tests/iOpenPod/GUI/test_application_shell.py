"""Structural tests for the reusable QWidget application shell."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QListView,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    build_context as _context,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    tracks as _tracks,
)

from iOpenPod.app.backups import BackupProgress, BackupStage
from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_DARK_THEME,
    APPEARANCE_LIGHT_THEME,
    APPEARANCE_MODE,
    COLORFUL_MODE,
    DRAFT_ALL_CHANGES,
    LIBRARY_SPLITTER_STATE,
    MAX_BACKUPS,
    PLAYER_POSITION,
    AppearanceMode,
    DarkTheme,
    LightTheme,
    PlayerPosition,
)
from iOpenPod.app.models.collection_list_model import (
    CollectionRole,
)
from iOpenPod.app.models.library_filter_models import AlbumFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackColumn
from iOpenPod.app.services.linux_identity import (
    UDEV_RULE_DESTINATION,
    UdevRuleStatus,
    UdevRuleStatusKind,
)
from iOpenPod.GUI.delegates.collection_list_delegate import CollectionListDelegate
from iOpenPod.GUI.dialogs.library_review import LibraryReviewDialog
from iOpenPod.GUI.dialogs.linux_identity_setup import LinuxIdentityUninstallDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.pages.podcast_page import PodcastPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.image_color import RGBColor
from iOpenPod.GUI.presentation.theme.dynamic import (
    colorful_card_fill,
    colorful_header_colors,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import SourceListPanel
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)
from iOpenPod.GUI.widgets.track_list_header import LibrarySplitter
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaType, Track


def test_draft_all_changes_setting_controls_review_visibility_immediately() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)
    try:
        combo = window.findChild(AppComboBox, "draftAllChangesCombo")
        review = window.findChild(QPushButton, "reviewLibraryChanges")
        assert combo is not None and review is not None
        assert combo.currentData() is False
        assert review.isHidden()

        combo.setCurrentIndex(combo.findData(True))
        assert context.settings.get(DRAFT_ALL_CHANGES) is True
        assert not review.isHidden()
        assert context.library_write_controller.draft_all_changes

        context.settings.reset_global(DRAFT_ALL_CHANGES)
        assert combo.currentData() is False
        assert review.isHidden()
        page = window.findChild(SettingsPage)
        assert page is not None
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert context.settings.get(DRAFT_ALL_CHANGES) is False
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_automatic_save_failure_opens_diagnostics_with_review_button_hidden() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)
    try:
        review = window.findChild(QPushButton, "reviewLibraryChanges")
        dialog = window.findChild(LibraryReviewDialog)
        assert review is not None and review.isHidden()
        assert dialog is not None and not dialog.isVisible()

        context.library_write_controller.automaticSaveFailed.emit()

        assert dialog.isVisible()
        assert review.isHidden()
        assert context.library_write_controller.request is None
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("auto_discover", [False, True])
def test_startup_does_not_open_music_import_progress(auto_discover: bool) -> None:
    context = _context()
    window = MainWindow(context, auto_discover=auto_discover)

    try:
        window.show()
        # The removed import dialog opened on Qt's timer even after hide().
        QTest.qWait(4_500)

        assert not [
            dialog.windowTitle()
            for dialog in window.findChildren(QProgressDialog)
            if dialog.isVisible()
        ]
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_shell_does_not_offer_add_music() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        assert window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        assert window.findChild(QPushButton, "addMusic") is None
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("position", tuple(PlayerPosition))
def test_application_status_drives_the_shared_window_status_bar(
    position: PlayerPosition,
) -> None:
    context = _context()
    context.settings.set_global(PLAYER_POSITION, position.value)
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        player = window.findChild(PlayerBar)
        assert player is not None and player.height() == LAYOUT.player_idle_height
        assert window.statusBar().parentWidget() is window
        assert window.statusBar().isVisible() and window.statusBar().height() > 0
        context.status.show("test", "Updating Podcasts…")
        APPLICATION.processEvents()

        assert window.statusBar().currentMessage() == "Updating Podcasts…"

        context.status.clear("test")
        APPLICATION.processEvents()

        assert "No Active iPod" in window.statusBar().currentMessage()
    finally:
        window.close()
        context.shutdown()


def test_backup_progress_drives_the_shared_window_status_bar() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        progress = window.findChild(QProgressBar, "backupStatusProgress")
        assert progress is not None
        assert progress.isHidden()

        context.backup_controller.progressChanged.emit(
            BackupProgress(
                BackupStage.CAPTURING,
                current=1,
                total=2,
                message="Capturing 1 of 2 files…",
                current_file="iPod_Control/Music/F00/song.m4a",
                completed_bytes=75,
                total_bytes=100,
            )
        )
        APPLICATION.processEvents()

        assert progress.isVisible()
        assert progress.maximum() == 10_000
        assert progress.value() == 7_500
        assert progress.toolTip() == "iPod_Control/Music/F00/song.m4a"
        assert window.statusBar().currentMessage() == "Capturing 1 of 2 files…"

        context.backup_controller.busyChanged.emit(False)
        APPLICATION.processEvents()

        assert progress.isHidden()
        assert progress.toolTip() == ""
        assert "No Active iPod" in window.statusBar().currentMessage()
    finally:
        window.close()
        context.shutdown()


def test_shell_contains_persistent_player_sidebar_and_all_routes() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(100))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        player = window.findChild(PlayerBar)
        pages = window.findChild(QStackedWidget, "pageStack")
        splitter = window.findChild(LibrarySplitter, "librarySplitter")
        assert player is not None
        assert player.height() == LAYOUT.player_idle_height
        assert pages is not None
        # Normalize Tags is a maintenance dialog, not an empty navigation page.
        assert pages.count() == len(PageId) - 1
        assert splitter is not None
        assert splitter.count() == 2
        assert splitter.handleWidth() == LAYOUT.track_list_handle_height
        assert splitter.track_header.isVisible()
        assert splitter.track_header.cursor().shape() is Qt.CursorShape.SizeVerCursor
        original_sizes = splitter.sizes()
        drag_origin = QPoint(4, splitter.track_header.height() // 2)
        QTest.mousePress(
            splitter.track_header,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            drag_origin,
        )
        QTest.mouseMove(
            splitter.track_header,
            drag_origin + QPoint(0, 36),
            delay=10,
        )
        QTest.mouseRelease(
            splitter.track_header,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            drag_origin + QPoint(0, 36),
        )
        APPLICATION.processEvents()
        assert splitter.sizes() != original_sizes

        browser_title = window.findChild(QLabel, "browserTitle")
        assert browser_title is not None
        assert browser_title.text() == "Albums"
        assert window.findChild(QLabel, "browserSummary") is None
        album_sort = window.findChild(AppComboBox, "albumSort")
        assert album_sort is not None
        assert album_sort.currentText() == "Album title"
        assert album_sort.currentData() == "title"

        table = window.findChild(TrackTable, "trackTable")
        assert table is not None
        table.setCurrentIndex(table.model().index(0, 0))
        APPLICATION.processEvents()
        player_title = window.findChild(QLabel, "playerTrackTitle")
        assert player_title is not None
        assert player_title.text() == "Nothing playing"

        context.track_model.replace_tracks(_tracks(20))
        APPLICATION.processEvents()
        assert player_title.text() == "Nothing playing"
        assert "No Active iPod" in window.statusBar().currentMessage()

        settings_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.SETTINGS.value
        )
        settings_button.click()
        APPLICATION.processEvents()
        assert player.isVisible()
        assert pages.currentWidget() is not None

        tracks_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.TRACKS.value
        )
        tracks_button.click()
        APPLICATION.processEvents()
        tracks_page = pages.currentWidget()
        assert tracks_page is not None
        tracks_title = tracks_page.findChild(QLabel, "tracksTitle")
        tracks_table = tracks_page.findChild(TrackTable)
        assert tracks_title is not None
        assert tracks_title.text() == "Tracks"
        tracks_filter = tracks_page.findChild(AppComboBox)
        assert tracks_filter is not None
        assert tracks_filter.isHidden()
        assert tracks_page.findChild(LibrarySplitter) is None
        assert tracks_table is not None
        assert tracks_table.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_player_position_setting_moves_the_existing_player() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)
    track = _tracks(1)[0]

    try:
        window.show()
        APPLICATION.processEvents()
        shell = window.centralWidget()
        player = window.findChild(PlayerBar)
        position_combo = window.findChild(AppComboBox, "playerPositionCombo")
        assert shell is not None
        shell_layout = shell.layout()
        assert shell_layout is not None
        assert player is not None
        assert position_combo is not None
        assert context.settings.get(PLAYER_POSITION) == PlayerPosition.TOP.value
        assert shell_layout.indexOf(player) == 0
        assert player.property("playerPosition") == PlayerPosition.TOP.value

        context.playback_controller.enqueue(track)
        bottom_index = position_combo.findData(PlayerPosition.BOTTOM.value)
        position_combo.setCurrentIndex(bottom_index)
        APPLICATION.processEvents()

        assert context.settings.get(PLAYER_POSITION) == PlayerPosition.BOTTOM.value
        assert shell_layout.indexOf(player) == shell_layout.count() - 1
        assert player.property("playerPosition") == PlayerPosition.BOTTOM.value
        assert window.findChild(PlayerBar) is player
        assert player.track == track

        top_index = position_combo.findData(PlayerPosition.TOP.value)
        position_combo.setCurrentIndex(top_index)
        APPLICATION.processEvents()
        assert shell_layout.indexOf(player) == 0
    finally:
        window.close()
        context.shutdown()


def test_saved_bottom_player_position_is_applied_during_composition() -> None:
    context = _context()
    context.settings.set_global(PLAYER_POSITION, PlayerPosition.BOTTOM.value)
    window = MainWindow(context, auto_discover=False)

    try:
        shell = window.centralWidget()
        player = window.findChild(PlayerBar)
        assert shell is not None
        shell_layout = shell.layout()
        assert shell_layout is not None
        assert player is not None
        assert shell_layout.indexOf(player) == shell_layout.count() - 1
        assert player.property("playerPosition") == PlayerPosition.BOTTOM.value
    finally:
        window.close()
        context.shutdown()


def test_settings_choose_mode_exact_themes_and_colorful_mode() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        mode = window.findChild(AppComboBox, "appearanceModeCombo")
        light_theme = window.findChild(AppComboBox, "lightThemeCombo")
        dark_theme = window.findChild(AppComboBox, "darkThemeCombo")
        colorful = window.findChild(AppComboBox, "colorfulModeCombo")
        max_backups = window.findChild(AppComboBox, "maxBackups")
        assert mode is not None
        assert light_theme is not None
        assert dark_theme is not None
        assert colorful is not None
        assert max_backups is not None
        assert mode.currentData() == AppearanceMode.SYSTEM.value
        assert light_theme.currentData() == LightTheme.PORCELAIN.value
        assert tuple(
            dark_theme.itemData(index) for index in range(dark_theme.count())
        ) == (
            DarkTheme.SLATE.value,
            DarkTheme.ORIGINAL.value,
        )
        assert colorful.currentData() is False
        assert max_backups.currentData() == 0

        mode.setCurrentIndex(mode.findData(AppearanceMode.DARK.value))
        dark_theme.setCurrentIndex(dark_theme.findData(DarkTheme.ORIGINAL.value))
        colorful.setCurrentIndex(colorful.findData(True))
        max_backups.setCurrentIndex(max_backups.findData(10))
        APPLICATION.processEvents()

        assert context.settings.get(APPEARANCE_MODE) == AppearanceMode.DARK.value
        assert (
            context.settings.get(APPEARANCE_LIGHT_THEME) == LightTheme.PORCELAIN.value
        )
        assert context.settings.get(APPEARANCE_DARK_THEME) == DarkTheme.ORIGINAL.value
        assert context.settings.get(COLORFUL_MODE) is True
        assert context.settings.get(MAX_BACKUPS) == 10
        assert context.theme_manager.effective_theme is DarkTheme.ORIGINAL
    finally:
        window.close()
        context.shutdown()


def test_settings_show_version_and_open_support_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iOpenPod.GUI.pages.settings_page as settings_page

    opened: list[str] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr(settings_page, "get_version", lambda: "2.3.4")
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        version = window.findChild(QLabel, "currentAppVersion")
        report_issue = window.findChild(ActionButton, "reportIssue")
        donate = window.findChild(ActionButton, "donate")
        assert version is not None
        assert report_issue is not None
        assert donate is not None
        assert version.text() == "2.3.4"

        report_issue.click()
        donate.click()
        APPLICATION.processEvents()

        assert opened == [
            "https://github.com/TheRealSavi/iOpenPod/issues",
            "https://ko-fi.com/johngibbons",
        ]
    finally:
        window.close()
        context.shutdown()


def test_linux_settings_check_and_review_local_udev_rule_uninstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iOpenPod.GUI.pages.settings_page as settings_page

    statuses = iter(
        (
            UdevRuleStatus(
                UdevRuleStatusKind.CURRENT,
                Path(UDEV_RULE_DESTINATION),
            ),
            UdevRuleStatus(
                UdevRuleStatusKind.CURRENT,
                Path(UDEV_RULE_DESTINATION),
            ),
            UdevRuleStatus(UdevRuleStatusKind.MISSING),
        )
    )
    checks: list[UdevRuleStatus] = []

    def inspect() -> UdevRuleStatus:
        status = next(statuses)
        checks.append(status)
        return status

    reviewed: list[None] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(settings_page, "inspect_udev_rule", inspect)

    def review(_dialog: LinuxIdentityUninstallDialog) -> int:
        reviewed.append(None)
        return 0

    monkeypatch.setattr(
        LinuxIdentityUninstallDialog,
        "exec",
        review,
    )
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        section = window.findChild(QWidget, "linuxHostIntegrationSection")
        check = window.findChild(ActionButton, "checkUdevRule")
        uninstall = window.findChild(ActionButton, "uninstallUdevRule")
        assert section is not None and not section.isHidden()
        assert check is not None
        assert uninstall is not None
        assert uninstall.kind is ActionButtonKind.DANGER
        assert uninstall.isEnabled()
        assert any(
            "Installed and current at" in label.text()
            for label in section.findChildren(QLabel)
        )

        uninstall.click()
        APPLICATION.processEvents()

        assert reviewed == [None]
        assert len(checks) == 2

        check.click()
        APPLICATION.processEvents()

        assert len(checks) == 3
        assert not uninstall.isEnabled()
        assert any(
            "Not installed" in label.text() for label in section.findChildren(QLabel)
        )
    finally:
        window.close()
        context.shutdown()


def test_colorful_mode_tints_album_card_fill_selection_and_track_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    context.track_model.replace_tracks(
        (
            Track(1, "First", "Artist", "Album One", 180_000, artwork_id=64),
            Track(2, "Second", "Artist", "Album Two", 180_000, artwork_id=65),
        )
    )
    window = MainWindow(context, auto_discover=False)

    try:
        provider = window.findChild(ArtworkPixmapProvider)
        grid = window.findChild(AlbumGridView, "albumGrid")
        splitter = window.findChild(LibrarySplitter, "librarySplitter")
        assert provider is not None
        assert grid is not None
        assert splitter is not None
        source_color: RGBColor = (216, 24, 80)

        def dominant_color(
            _artwork_id: int,
            _logical_size: int,
            _device_pixel_ratio: float,
        ) -> RGBColor:
            return source_color

        monkeypatch.setattr(provider, "dominant_color", dominant_color)
        context.theme_manager.set_colorful_mode(True)
        window.resize(1100, 760)
        window.show()
        APPLICATION.processEvents()

        index = grid.model().index(0, 0)
        item_rect = grid.visualRect(index)
        other_rect = grid.visualRect(grid.model().index(1, 0))
        card_height = _card_size_hint(grid).height()
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            item_rect.center(),
        )
        APPLICATION.processEvents()

        card_left = item_rect.left() + (
            (item_rect.width() - LAYOUT.album_card_width) // 2
        )
        card_top = item_rect.top() + ((item_rect.height() - card_height) // 2)
        other_card_left = other_rect.left() + (
            (other_rect.width() - LAYOUT.album_card_width) // 2
        )
        other_card_top = other_rect.top() + ((other_rect.height() - card_height) // 2)
        grid_image = grid.viewport().grab().toImage()
        expected_fill = colorful_card_fill(
            source_color,
            context.theme_manager.tokens,
        )
        expected_selected_fill = colorful_card_fill(
            source_color,
            context.theme_manager.tokens,
            emphasized=True,
        )
        assert (
            grid_image.pixelColor(
                other_card_left + LAYOUT.space_2xs,
                other_card_top + (card_height // 2),
            )
            == expected_fill
        )
        assert (
            grid_image.pixelColor(
                card_left + (LAYOUT.album_card_width // 2),
                card_top + card_height - LAYOUT.space_xs,
            )
            == expected_selected_fill
        )
        header = splitter.track_header
        header_image = header.grab().toImage()
        expected_header = colorful_header_colors(
            source_color,
            context.theme_manager.tokens,
        )
        assert header_image.pixelColor(4, header.height() // 2) == expected_header.fill
    finally:
        window.close()
        context.shutdown()


def test_library_views_use_virtualized_model_view_primitives() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(10_000))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        grid = window.findChild(AlbumGridView, "albumGrid")
        table = window.findChild(TrackTable, "trackTable")
        assert grid is not None
        assert grid.layoutMode() is QListView.LayoutMode.Batched
        assert grid.uniformItemSizes()
        grid_model = grid.model()
        assert grid_model.rowCount() == 1_000
        first_album_rect = grid.visualRect(grid_model.index(0, 0))
        first_row_count = sum(
            grid.visualRect(grid_model.index(row, 0)).top() == first_album_rect.top()
            for row in range(grid_model.rowCount())
        )
        assert 1 <= grid.batchSize() <= 64
        assert grid.batchSize() % first_row_count == 0
        QTest.mouseMove(grid.viewport(), first_album_rect.center())
        APPLICATION.processEvents()
        assert grid.viewport().cursor().shape() is Qt.CursorShape.PointingHandCursor

        assert table is not None
        table_model = table.model()
        assert table_model.rowCount() == 10_000
        assert table.horizontalHeader().sectionsMovable()
        assert table.horizontalHeader().sortIndicatorSection() == TrackColumn.ALBUM
        assert (
            table.horizontalHeader().sectionResizeMode(1)
            is QHeaderView.ResizeMode.Interactive
        )
        assert table.verticalScrollMode() is table.ScrollMode.ScrollPerItem
        assert table.selectionBehavior() is table.SelectionBehavior.SelectRows
        index_widget: QWidget | None = table.indexWidget(table_model.index(0, 0))
        assert index_widget is None
    finally:
        window.close()
        context.shutdown()


def test_library_grids_equalize_cells_without_churning_model_state() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(100))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        grid = window.findChild(AlbumGridView, "albumGrid")
        assert grid is not None
        _assert_grid_resize_is_stable(grid)

        artists_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.ARTISTS.value
        )
        artists_button.click()
        APPLICATION.processEvents()
        collection_grid = window.findChild(
            CollectionGridView,
            "artistsCollectionGrid",
        )
        assert collection_grid is not None
        _assert_grid_resize_is_stable(collection_grid)
    finally:
        window.close()
        context.shutdown()


def test_artist_album_grid_does_not_collapse_at_exact_fit_widths() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(100))
    window = MainWindow(context, auto_discover=False)

    try:
        window.resize(960, 800)
        window.show()
        artists_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.ARTISTS.value
        )
        artists_button.click()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None
        page = pages.currentWidget()
        assert page is not None

        list_button = next(
            button
            for button in page.findChildren(IconButton)
            if button.accessibleName() == "List view"
        )
        list_button.click()
        APPLICATION.processEvents()

        grid = page.findChild(AlbumGridView, "artistsAlbumGrid")
        assert grid is not None
        model = grid.model()
        minimum_cell_width = LAYOUT.album_card_width + LAYOUT.space_md
        exact_fit_widths_checked = 0

        for window_width in range(960, 1_060):
            window.resize(window_width, 800)
            APPLICATION.processEvents()
            viewport_width = grid.viewport().width()
            column_count = max(1, viewport_width // minimum_cell_width)
            if column_count < 2 or viewport_width % column_count != 0:
                continue

            APPLICATION.processEvents()
            first_rect = grid.visualRect(model.index(0, 0))
            last_rect = grid.visualRect(model.index(column_count - 1, 0))
            assert last_rect.top() == first_rect.top()
            assert grid.gridSize().width() * column_count < viewport_width

            exact_fit_widths_checked += 1
            if exact_fit_widths_checked == 3:
                break

        assert exact_fit_widths_checked == 3
    finally:
        window.close()
        context.shutdown()


def test_large_artist_album_grid_reflows_in_the_resize_event_turn() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(10_000))
    window = MainWindow(context, auto_discover=False)

    try:
        window.resize(960, 800)
        window.show()
        artists_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.ARTISTS.value
        )
        artists_button.click()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None
        page = pages.currentWidget()
        assert page is not None

        list_button = next(
            button
            for button in page.findChildren(IconButton)
            if button.accessibleName() == "List view"
        )
        list_button.click()
        for _ in range(3):
            APPLICATION.processEvents()

        grid = page.findChild(AlbumGridView, "artistsAlbumGrid")
        assert grid is not None
        model = grid.model()
        minimum_cell_width = LAYOUT.album_card_width + LAYOUT.space_md

        for expected_columns in (3, 4, 3):
            target_viewport_width = (
                expected_columns * minimum_cell_width
            ) + _grid_wrap_reserve(grid)
            width_delta = target_viewport_width - grid.viewport().width()
            window.resize(window.width() + width_delta, window.height())
            APPLICATION.processEvents()

            assert grid.viewport().width() == target_viewport_width
            first_top = grid.visualRect(model.index(0, 0)).top()
            actual_columns = sum(
                grid.visualRect(model.index(row, 0)).top() == first_top
                for row in range(expected_columns + 1)
            )
            assert actual_columns == expected_columns
    finally:
        window.close()
        context.shutdown()


def test_album_grid_keeps_rows_aligned_across_layout_batches() -> None:
    context = _context()
    grid = _standalone_album_grid(context, 130)

    try:
        grid.resize(922, 500)
        grid.show()

        for target_viewport_width in (920, 1_100, 1_280, 920):
            _settle_grid(grid)
            grid.resize(
                grid.width() + target_viewport_width - grid.viewport().width(),
                grid.height(),
            )
            _settle_grid(grid)

            assert grid.viewport().width() == target_viewport_width
            _assert_grid_rows_aligned(grid)
    finally:
        grid.close()
        context.shutdown()


def test_album_grid_settles_without_a_scrollbar_when_all_cards_fit() -> None:
    context = _context()
    grid = _standalone_album_grid(context, 4)

    try:
        grid.resize(900, 300)
        grid.show()
        _settle_grid(grid)

        samples: list[tuple[int, bool, int, tuple[tuple[int, int], ...]]] = []
        for _ in range(12):
            APPLICATION.processEvents()
            samples.append(_grid_geometry(grid))

        assert len(set(samples)) == 1
        _, scrollbar_visible, scrollbar_maximum, positions = samples[0]
        assert not scrollbar_visible
        assert scrollbar_maximum == 0
        assert len({top for _, top in positions}) == 1
    finally:
        grid.close()
        context.shutdown()


def test_album_grid_restores_its_no_scroll_formation_after_model_shrinks() -> None:
    context = _context()
    grid = _standalone_album_grid(context, 4)

    try:
        grid.resize(
            6 * (LAYOUT.album_card_width + LAYOUT.space_md) + LAYOUT.space_lg,
            2 * grid.gridSize().height() + LAYOUT.space_lg,
        )
        grid.show()
        _settle_grid(grid)

        context.track_model.replace_tracks(_album_grid_tracks(12))
        _settle_grid(grid)
        initial = _grid_geometry(grid)
        assert not initial[1]
        assert initial[2] == 0

        context.track_model.replace_tracks(_album_grid_tracks(130))
        _settle_grid(grid)
        assert grid.verticalScrollBar().isVisible()

        context.track_model.replace_tracks(_album_grid_tracks(12))
        _settle_grid(grid)
        recovered = tuple(_grid_geometry(grid) for _ in range(4))

        assert all(sample == initial for sample in recovered)
    finally:
        grid.close()
        context.shutdown()


def test_album_grid_recalculates_cells_when_scrollbar_style_changes() -> None:
    context = _context()
    grid = _standalone_album_grid(context, 6)

    try:
        grid.resize(1_000, 1_200)
        grid.show()
        _settle_grid(grid)
        initial_grid_size = grid.gridSize()

        grid.setStyleSheet("QScrollBar:vertical { width: 80px; }")
        _settle_grid(grid)

        layout_width = max(
            1,
            grid.viewport().width() - _grid_wrap_reserve(grid),
        )
        minimum_cell_width = LAYOUT.album_card_width + LAYOUT.space_md
        column_count = max(1, layout_width // minimum_cell_width)
        expected_cell_width = max(
            LAYOUT.album_card_width,
            layout_width // column_count,
        )
        assert grid.gridSize() != initial_grid_size
        assert grid.gridSize() == QSize(
            expected_cell_width,
            _card_size_hint(grid).height() + LAYOUT.space_xs,
        )
        assert grid.batchSize() % column_count == 0
        _assert_grid_rows_aligned(grid)
    finally:
        grid.close()
        context.shutdown()


def test_album_grid_uses_final_viewport_width_after_scrollbar_appears() -> None:
    context = _context()
    grid = _standalone_album_grid(context, 260)

    try:
        grid.resize(920, 500)
        grid.show()
        _settle_grid(grid)

        assert grid.verticalScrollBar().isVisible()
        layout_width = max(
            1,
            grid.viewport().width() - _grid_wrap_reserve(grid),
        )
        minimum_cell_width = LAYOUT.album_card_width + LAYOUT.space_md
        column_count = max(1, layout_width // minimum_cell_width)
        expected_cell_width = max(
            LAYOUT.album_card_width,
            layout_width // column_count,
        )
        assert grid.gridSize() == QSize(
            expected_cell_width,
            _card_size_hint(grid).height() + LAYOUT.space_xs,
        )
        assert grid.batchSize() % column_count == 0
        _assert_grid_rows_aligned(grid)
    finally:
        grid.close()
        context.shutdown()


def _standalone_album_grid(context: AppContext, album_count: int) -> AlbumGridView:
    context.track_model.replace_tracks(_album_grid_tracks(album_count))
    model = AlbumFilterProxyModel(context.album_model)
    artwork_provider = ArtworkPixmapProvider(context.artwork_controller)
    grid = AlbumGridView(model, context.theme_manager, artwork_provider)
    model.setParent(grid)
    artwork_provider.setParent(grid)
    return grid


def _settle_grid(grid: QListView) -> None:
    for _ in range(24):
        APPLICATION.processEvents()
    assert grid.model().rowCount() > 0


def _grid_geometry(
    grid: QListView,
) -> tuple[int, bool, int, tuple[tuple[int, int], ...]]:
    model = grid.model()
    positions = tuple(
        (
            grid.visualRect(model.index(row, 0)).left(),
            grid.visualRect(model.index(row, 0)).top(),
        )
        for row in range(model.rowCount())
    )
    return (
        grid.viewport().width(),
        grid.verticalScrollBar().isVisible(),
        grid.verticalScrollBar().maximum(),
        positions,
    )


def _assert_grid_rows_aligned(grid: QListView) -> None:
    model = grid.model()
    rows_by_top: dict[int, list[int]] = {}
    for row in range(model.rowCount()):
        rect = grid.visualRect(model.index(row, 0))
        assert rect.isValid()
        rows_by_top.setdefault(rect.top(), []).append(rect.left())

    rows = [lefts for _, lefts in sorted(rows_by_top.items())]
    assert rows
    expected_lefts = tuple(rows[0])
    assert len(expected_lefts) > 1
    for lefts in rows[:-1]:
        assert tuple(lefts) == expected_lefts
    assert tuple(rows[-1]) == expected_lefts[: len(rows[-1])]


def _assert_grid_resize_is_stable(grid: QListView) -> None:
    model = grid.model()
    current = model.index(min(2, model.rowCount() - 1), 0)
    grid.setCurrentIndex(current)
    model_resets = QSignalSpy(model.modelReset)
    model_relayouts = QSignalSpy(model.layoutChanged)
    assert grid.resizeMode() is QListView.ResizeMode.Fixed

    for width in (947, 735, 736, 919, 920, 1_181, 947, 947):
        grid.resize(width, grid.height())
        APPLICATION.processEvents()
        layout_width = max(
            1,
            grid.viewport().width() - _grid_wrap_reserve(grid),
        )
        minimum_cell_width = LAYOUT.album_card_width + LAYOUT.space_md
        column_count = max(1, layout_width // minimum_cell_width)
        expected_cell_width = max(
            LAYOUT.album_card_width,
            layout_width // column_count,
        )

        assert grid.gridSize() == QSize(
            expected_cell_width,
            _card_size_hint(grid).height() + LAYOUT.space_xs,
        )
        assert grid.currentIndex() == current

    assert model_resets.count() == 0
    assert model_relayouts.count() == 0


def _grid_wrap_reserve(grid: QListView) -> int:
    scrollbar = grid.verticalScrollBar()
    scrollbar_extent = grid.style().pixelMetric(
        QStyle.PixelMetric.PM_ScrollBarExtent,
        None,
        scrollbar,
    )
    return 1 if scrollbar.isVisible() else max(1, scrollbar_extent) + 1


def _card_size_hint(grid: QListView) -> QSize:
    option = QStyleOptionViewItem()
    option.initFrom(grid)
    option.font = grid.font()
    return grid.itemDelegate().sizeHint(option, QModelIndex())


def test_album_grid_has_no_outer_view_padding() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(100))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        grid = window.findChild(AlbumGridView, "albumGrid")
        assert grid is not None
        margins = grid.contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == (0, 0, 0, 0)
    finally:
        window.close()
        context.shutdown()


def test_implemented_library_routes_are_distinct_real_pages() -> None:
    context = _context()
    context.track_model.replace_tracks(_media_tracks())
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None

        expected_tables = {
            PageId.TRACKS: ("tracks", 5),
            PageId.ARTISTS: ("artists-tracks", 1),
            PageId.GENRES: ("genres-tracks", 1),
            PageId.AUDIOBOOKS: ("audiobooks", 1),
            PageId.MOVIES: ("movies", 1),
            PageId.TV_SHOWS: ("tv-shows-tracks", 1),
            PageId.MUSIC_VIDEOS: ("music-videos-tracks", 1),
            PageId.VIDEOS: ("videos", 3),
        }
        seen_pages: set[QWidget] = set()
        for page_id, (table_id, row_count) in expected_tables.items():
            button = next(
                candidate
                for candidate in window.findChildren(QPushButton)
                if candidate.property("pageId") == page_id.value
            )
            button.click()
            APPLICATION.processEvents()
            page = pages.currentWidget()
            assert page is not None
            assert page not in seen_pages
            seen_pages.add(page)
            table = page.findChild(TrackTable)
            assert table is not None
            assert table.property("tableId") == table_id
            assert table.model().rowCount() == row_count

        podcast_button = next(
            candidate
            for candidate in window.findChildren(QPushButton)
            if candidate.property("pageId") == PageId.PODCASTS.value
        )
        podcast_button.click()
        APPLICATION.processEvents()
        assert isinstance(pages.currentWidget(), PodcastPage)

        photo_button = next(
            candidate
            for candidate in window.findChildren(QPushButton)
            if candidate.property("pageId") == PageId.PHOTOS.value
        )
        photo_button.click()
        APPLICATION.processEvents()
        assert isinstance(pages.currentWidget(), PhotoPage)
    finally:
        window.close()
        context.shutdown()


def test_library_toolbar_titles_share_the_albums_heading_style() -> None:
    context = _context()
    context.track_model.replace_tracks(_media_tracks())
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        albums_title = window.findChild(QLabel, "browserTitle")
        assert pages is not None
        assert albums_title is not None
        expected_font = albums_title.font()

        for page_id in (
            PageId.ARTISTS,
            PageId.GENRES,
            PageId.TRACKS,
            PageId.AUDIOBOOKS,
            PageId.MOVIES,
            PageId.TV_SHOWS,
            PageId.MUSIC_VIDEOS,
            PageId.VIDEOS,
        ):
            button = next(
                candidate
                for candidate in window.findChildren(QPushButton)
                if candidate.property("pageId") == page_id.value
            )
            button.click()
            APPLICATION.processEvents()
            page = pages.currentWidget()
            assert page is not None
            title = page.findChild(QLabel, f"{page_id.value}Title")
            assert title is not None
            assert title.font().family() == expected_font.family()
            assert title.font().pointSizeF() == expected_font.pointSizeF()
            assert title.font().weight() == expected_font.weight()
    finally:
        window.close()
        context.shutdown()


def test_collection_sort_options_are_page_specific_and_drive_the_grid() -> None:
    context = _context()
    context.track_model.replace_tracks(
        (
            Track(1, "One", "Alpha", "Only", 1, genre="Ambient"),
            Track(2, "Two", "Zulu", "First", 1, genre="Rock"),
            Track(3, "Three", "Zulu", "Second", 1, genre="Rock"),
            *_media_tracks(),
        )
    )
    window = MainWindow(context, auto_discover=False)
    expected_options = {
        PageId.ARTISTS: (
            ("Artist name", "title"),
            ("Most albums", "item_count"),
            ("Most tracks", "track_count"),
            ("", None),
            ("Ascending", "__sort_ascending__"),
            ("Descending", "__sort_descending__"),
        ),
        PageId.GENRES: (
            ("Genre name", "title"),
            ("Most albums", "item_count"),
            ("Most tracks", "track_count"),
            ("", None),
            ("Ascending", "__sort_ascending__"),
            ("Descending", "__sort_descending__"),
        ),
        PageId.TV_SHOWS: (
            ("Show name", "title"),
            ("Most episodes", "item_count"),
            ("Longest duration", "duration"),
            ("", None),
            ("Ascending", "__sort_ascending__"),
            ("Descending", "__sort_descending__"),
        ),
        PageId.MUSIC_VIDEOS: (
            ("Album title", "title"),
            ("Most videos", "track_count"),
            ("Longest duration", "duration"),
            ("", None),
            ("Ascending", "__sort_ascending__"),
            ("Descending", "__sort_descending__"),
        ),
    }

    try:
        window.show()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None

        for page_id, expected in expected_options.items():
            button = next(
                candidate
                for candidate in window.findChildren(QPushButton)
                if candidate.property("pageId") == page_id.value
            )
            button.click()
            APPLICATION.processEvents()
            page = pages.currentWidget()
            assert page is not None
            sort = page.findChild(AppComboBox, f"{page_id.value}Sort")
            assert sort is not None
            assert sort.isVisible()
            assert (
                tuple(
                    (sort.itemText(index), sort.itemData(index))
                    for index in range(sort.count())
                )
                == expected
            )
            assert sort.currentText() == expected[0][0]
            assert sort.currentData() == expected[0][1]
            separator = sort.model().index(len(expected) - 3, 0)
            assert not sort.model().flags(separator) & Qt.ItemFlag.ItemIsEnabled

        artists_button = next(
            candidate
            for candidate in window.findChildren(QPushButton)
            if candidate.property("pageId") == PageId.ARTISTS.value
        )
        artists_button.click()
        APPLICATION.processEvents()
        artists_page = pages.currentWidget()
        assert artists_page is not None
        artist_sort = artists_page.findChild(AppComboBox, "artistsSort")
        artist_grid = artists_page.findChild(
            CollectionGridView,
            "artistsCollectionGrid",
        )
        assert artist_sort is not None
        assert artist_grid is not None
        artist_sort.setCurrentIndex(artist_sort.findData("item_count"))
        APPLICATION.processEvents()
        assert artist_grid.model().index(0, 0).data(CollectionRole.TITLE) == "Zulu"

        artist_sort.setCurrentIndex(artist_sort.findText("Descending"))
        APPLICATION.processEvents()
        first_count = artist_grid.model().index(0, 0).data(CollectionRole.ITEM_COUNT)
        last_count = (
            artist_grid.model()
            .index(
                artist_grid.model().rowCount() - 1,
                0,
            )
            .data(CollectionRole.ITEM_COUNT)
        )
        assert isinstance(first_count, int) and isinstance(last_count, int)
        assert first_count <= last_count
        assert artist_sort.currentData() == "item_count"

        artist_sort.setCurrentIndex(artist_sort.findText("Ascending"))
        APPLICATION.processEvents()
        first_count = artist_grid.model().index(0, 0).data(CollectionRole.ITEM_COUNT)
        last_count = (
            artist_grid.model()
            .index(
                artist_grid.model().rowCount() - 1,
                0,
            )
            .data(CollectionRole.ITEM_COUNT)
        )
        assert isinstance(first_count, int) and isinstance(last_count, int)
        assert first_count >= last_count
        assert artist_sort.currentData() == "item_count"
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize(
    ("page_id", "prefix"),
    (
        (PageId.ARTISTS, "artists"),
        (PageId.GENRES, "genres"),
    ),
)
def test_collection_list_view_filters_album_grid_without_becoming_tracks(
    page_id: PageId,
    prefix: str,
) -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(40))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        page_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == page_id.value
        )
        page_button.click()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None
        page = pages.currentWidget()
        assert page is not None

        list_button = next(
            button
            for button in page.findChildren(IconButton)
            if button.accessibleName() == "List view"
        )
        list_button.click()
        APPLICATION.processEvents()

        browser = page.findChild(QStackedWidget, f"{prefix}BrowserStack")
        collection_grid = page.findChild(
            CollectionGridView,
            f"{prefix}CollectionGrid",
        )
        collection_list = page.findChild(QListView, f"{prefix}CollectionList")
        collection_panel = page.findChild(
            SourceListPanel,
            f"{prefix}CollectionPanel",
        )
        collection_count = page.findChild(QLabel, f"{prefix}CollectionCount")
        album_grid = page.findChild(AlbumGridView, f"{prefix}AlbumGrid")
        table = page.findChild(TrackTable)
        assert browser is not None
        assert collection_grid is not None
        assert collection_list is not None
        assert collection_panel is not None
        assert collection_count is not None
        assert album_grid is not None
        assert table is not None
        assert browser.currentIndex() == 1
        assert collection_panel.property("sourceListPanel") is True
        assert collection_panel.minimumWidth() == LAYOUT.source_list_minimum_width
        assert collection_panel.maximumWidth() == LAYOUT.source_list_maximum_width
        assert collection_count.text() == str(collection_list.model().rowCount())
        assert isinstance(collection_list.itemDelegate(), CollectionListDelegate)
        assert collection_list.viewMode() is QListView.ViewMode.ListMode
        assert collection_list.flow() is QListView.Flow.TopToBottom
        assert not collection_list.isWrapping()
        assert collection_list.uniformItemSizes()
        assert collection_list.sizeHintForRow(0) == LAYOUT.collection_list_row_height
        assert not bool(
            collection_list.indexWidget(collection_list.model().index(0, 0))
        )

        collection_list.setCurrentIndex(collection_list.model().index(0, 0))
        APPLICATION.processEvents()
        assert collection_grid.currentIndex().row() == 0
        assert album_grid.model().rowCount() == 1
        assert table.model().rowCount() == 10
    finally:
        window.close()
        context.shutdown()


def test_track_table_layout_is_saved_per_named_instance() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(20))
    first = MainWindow(context, auto_discover=False)

    try:
        table = first.findChild(TrackTable, "trackTable")
        assert table is not None
        header = table.horizontalHeader()
        header.moveSection(header.visualIndex(2), 0)
        table.setColumnHidden(4, True)
        table.save_layout()

        second = MainWindow(context, auto_discover=False)
        try:
            restored = second.findChild(TrackTable, "trackTable")
            assert restored is not None
            assert restored.horizontalHeader().visualIndex(2) == 0
            assert restored.isColumnHidden(4)
        finally:
            second.close()
    finally:
        first.close()
        context.shutdown()


def test_player_transport_uses_flat_emphasis_without_accent_fill() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(1))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        table = window.findChild(TrackTable, "trackTable")
        assert table is not None
        table.doubleClicked.emit(table.model().index(0, 0))
        APPLICATION.processEvents()
        previous = window.findChild(IconButton, "playerPrevious")
        play_button = window.findChild(IconButton, "playerPlayPause")
        next_button = window.findChild(IconButton, "playerNext")
        assert previous is not None
        assert play_button is not None
        assert next_button is not None
        assert play_button.isEnabled()
        assert previous.kind is IconButtonKind.SUBTLE
        assert play_button.kind is IconButtonKind.QUIET
        assert next_button.kind is IconButtonKind.SUBTLE
        assert not bool(play_button.property("primary"))

        rendered = play_button.grab().toImage()
        accent = QColor(context.theme_manager.tokens.accent)
        assert all(
            rendered.pixelColor(x, y) != accent
            for y in range(rendered.height())
            for x in range(rendered.width())
        )
    finally:
        window.close()
        context.shutdown()


def test_player_clears_on_a_whole_library_snapshot_with_reused_track_ids() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(1))
    window = MainWindow(context, auto_discover=False)

    try:
        table = window.findChild(TrackTable, "trackTable")
        player_title = window.findChild(QLabel, "playerTrackTitle")
        assert table is not None
        assert player_title is not None
        table.doubleClicked.emit(table.model().index(0, 0))
        APPLICATION.processEvents()
        assert player_title.text() == "Track 00000"

        context.track_model.reset_tracks(
            (Track(0, "Different Library", "Artist", "Album", 1),)
        )
        APPLICATION.processEvents()

        assert player_title.text() == "Nothing playing"
    finally:
        window.close()
        context.shutdown()


def test_view_mode_selector_is_inset_within_the_browser_header() -> None:
    context = _context()
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        artists_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.ARTISTS.value
        )
        artists_button.click()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None
        page = pages.currentWidget()
        assert page is not None

        toolbar = page.findChild(QWidget, "artistsToolbar")
        selector = page.findChild(QWidget, "artistsViewModes")
        assert toolbar is not None
        assert selector is not None
        top_inset = selector.geometry().top() - toolbar.contentsRect().top()
        bottom_inset = toolbar.contentsRect().bottom() - selector.geometry().bottom()
        assert top_inset >= LAYOUT.space_xs
        assert bottom_inset >= LAYOUT.space_xs
    finally:
        window.close()
        context.shutdown()


def test_browser_and_track_searches_keep_separate_contexts() -> None:
    context = _context()
    context.track_model.replace_tracks(_tracks(30))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        splitter = window.findChild(LibrarySplitter, "librarySplitter")
        grid = window.findChild(AlbumGridView, "albumGrid")
        table = window.findChild(TrackTable, "trackTable")
        browser_search = window.findChild(SearchField, "librarySearch")
        assert splitter is not None
        assert grid is not None
        assert table is not None
        assert browser_search is not None

        track_header = splitter.track_header
        track_title = track_header.findChild(QLabel, "trackListTitle")
        track_search = track_header.findChild(SearchField, "trackListSearch")
        assert track_title is not None
        assert track_search is not None
        assert track_title.text() == "All Tracks"
        assert track_header.findChild(QLabel, "trackListCount") is None
        assert not track_header.findChildren(QPushButton)
        assert track_search.cursor().shape() is Qt.CursorShape.IBeamCursor

        browser_search.setText("Album 0001")
        QTest.qWait(220)
        APPLICATION.processEvents()
        assert grid.model().rowCount() == 1
        assert table.model().rowCount() == 30

        browser_search.setText("")
        QTest.qWait(220)
        APPLICATION.processEvents()
        first_album = grid.model().index(0, 0)
        grid.setCurrentIndex(first_album)
        APPLICATION.processEvents()
        assert track_title.text() == "Album 0000"
        assert table.model().rowCount() == 10

        track_search.setText("Track 00003")
        QTest.qWait(220)
        APPLICATION.processEvents()
        assert table.model().rowCount() == 1
        assert grid.model().rowCount() == 3
    finally:
        window.close()
        context.shutdown()


def test_legacy_splitter_state_cannot_collapse_track_title_bar() -> None:
    legacy_splitter = QSplitter(Qt.Orientation.Vertical)
    legacy_splitter.setHandleWidth(4)
    legacy_splitter.addWidget(QWidget())
    legacy_splitter.addWidget(QWidget())
    legacy_splitter.setSizes([480, 300])
    legacy_state = legacy_splitter.saveState()
    legacy_splitter.close()

    context = _context()
    context.settings.set_global(LIBRARY_SPLITTER_STATE, legacy_state)
    context.track_model.replace_tracks(_tracks(30))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()

        splitter = window.findChild(LibrarySplitter, "librarySplitter")
        assert splitter is not None
        track_title = splitter.track_header.findChild(QLabel, "trackListTitle")
        track_search = splitter.track_header.findChild(
            SearchField,
            "trackListSearch",
        )
        assert track_title is not None
        assert track_search is not None
        assert splitter.handleWidth() == LAYOUT.track_list_handle_height
        assert splitter.track_header.height() >= LAYOUT.track_list_handle_height
        assert track_title.height() >= track_title.sizeHint().height()
        assert track_search.height() >= track_search.minimumSizeHint().height()
    finally:
        window.close()
        context.shutdown()


def test_reusable_controls_use_semantic_pointer_cursors() -> None:
    button = IconButton("grid", "Grid view")
    combo = AppComboBox()
    search = SearchField()
    try:
        assert button.cursor().shape() is Qt.CursorShape.PointingHandCursor
        assert combo.cursor().shape() is Qt.CursorShape.PointingHandCursor
        assert search.cursor().shape() is Qt.CursorShape.IBeamCursor

        button.setEnabled(False)
        combo.setEnabled(False)
        search.setEnabled(False)
        APPLICATION.processEvents()
        assert button.cursor().shape() is Qt.CursorShape.ArrowCursor
        assert combo.cursor().shape() is Qt.CursorShape.ArrowCursor
        assert search.cursor().shape() is Qt.CursorShape.ArrowCursor
    finally:
        button.close()
        combo.close()
        search.close()


def _album_grid_tracks(count: int) -> tuple[Track, ...]:
    return tuple(
        Track(
            track_id=index,
            title=f"Track {index:05d}",
            artist=f"Artist {index:05d}",
            album=f"Album {index:05d}",
            length_ms=180_000,
            artwork_id=index + 1 if index % 2 else 0,
        )
        for index in range(count)
    )


def _media_tracks() -> tuple[Track, ...]:

    return (
        Track(1, "Song", "Artist", "Album", 1_000, artwork_id=11),
        Track(2, "Book", "Author", "Book", 1_000, media_types=(MediaType.AUDIOBOOK,)),
        Track(3, "Movie", "Director", "Movie", 1_000, media_types=(MediaType.VIDEO,)),
        Track(
            4,
            "Episode",
            "Cast",
            "Season 1",
            1_000,
            media_types=(MediaType.TV_SHOW,),
            show="Show",
            episode="Pilot",
        ),
        Track(
            5,
            "Video",
            "Artist",
            "Video Album",
            1_000,
            media_types=(MediaType.MUSIC_VIDEO,),
        ),
    )
