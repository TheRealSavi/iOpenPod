"""TV Show cards and inline seasons share Library navigation and Track actions."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt, QVariantAnimation
from PySide6.QtGui import QDrag
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QTabBar, QToolButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.models.collection_list_model import CollectionRole, CollectionSummary
from iOpenPod.app.models.library_drag import dropped_tracks
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.collection_detail import CollectionDetailPage
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.inline_album_expansion import InlineAlbumExpansion
from iOpenPod.GUI.widgets.inline_tv_show_panel import InlineTVShowPanel
from iOpenPod.GUI.widgets.library_content import LibraryContent
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata


def _episode(track_id: int, season: int, episode: int, artwork: int = 0) -> Track:
    return Track(
        track_id,
        f"Episode title {track_id}",
        "",
        f"Season {season}",
        2_580_000,
        show="The Show",
        season_number=season,
        episode_number=episode,
        artwork_id=artwork,
        media_types=(MediaType.TV_SHOW,),
        year=2000 + season,
        metadata=TrackMetadata(
            release_date=int(datetime(2000 + season, 1, 10, tzinfo=UTC).timestamp()),
            description="A long description with emoji 🎬 and ordinary words. " * 30,
        ),
    )


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    tracks = (
        _episode(1, 10, 1, 101),
        _episode(2, 1, 1),
        _episode(3, 1, 2, 103),
        _episode(4, 1, 3, 104),
        _episode(5, 2, 1, 105),
        _episode(6, 2, 2, 106),
        Track(99, "Music", "Artist", "Album", 1000, show="The Show"),
    )
    context.library_workspace.load(LibrarySnapshot(tracks))
    context.track_model.reset_tracks(tracks)
    yield context
    context.shutdown()


def _page(context: AppContext) -> CollectionPage:
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = CollectionPage(
        context.track_model,
        context.tv_show_model,
        context.settings,
        context.theme_manager,
        provider,
        page_id=PageId.TV_SHOWS,
        table_id="test-tv-shows",
    )
    provider.setParent(page)
    page.resize(1200, 850)
    page.show()
    QTest.qWait(100)
    return page


def _finish_expansion(page: CollectionPage) -> None:
    animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
    assert animation is not None
    animation.setCurrentTime(animation.duration())
    APPLICATION.processEvents()


def _click_show(grid: CollectionGridView) -> None:
    # Send fresh modifiers with the click instead of inheriting Qt's last input
    # state through a directly emitted clicked signal.
    QTest.mouseClick(
        grid.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        grid.visualRect(grid.model().index(0, 0)).center(),
    )


def _open(
    page: CollectionPage,
) -> tuple[CollectionGridView, InlineTVShowPanel, QTabBar]:
    grid = page.findChild(CollectionGridView)
    panel = page.findChild(InlineTVShowPanel)
    assert grid is not None and panel is not None
    _click_show(grid)
    _finish_expansion(page)
    tabs = panel.findChild(QTabBar)
    assert tabs is not None and panel.isVisible()
    return grid, panel, tabs


def _ids(view: TrackTable | InlineTVShowPanel) -> list[int]:
    model = (
        view.track_view.model() if isinstance(view, InlineTVShowPanel) else view.model()
    )
    return [
        model.index(row, 0).data(TrackRole.TRACK_ID) for row in range(model.rowCount())
    ]


@pytest.mark.parametrize(
    "modifiers",
    [Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier],
)
def test_plain_click_opens_show_after_modified_selection(
    context: AppContext, modifiers: Qt.KeyboardModifier
) -> None:
    page = _page(context)
    try:
        grid = page.findChild(CollectionGridView)
        panel = page.findChild(InlineTVShowPanel)
        assert grid is not None and panel is not None
        index = grid.model().index(0, 0)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            modifiers,
            grid.visualRect(index).center(),
        )
        _finish_expansion(page)
        assert not panel.isVisible()

        _open(page)
        assert panel.isVisible()
    finally:
        page.close()
        page.deleteLater()


def test_season_tabs_keep_expansion_and_switch_episode_artwork_and_colors(
    context: AppContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colors = {103: (200, 70, 40), 105: (30, 110, 210), 101: (80, 190, 90)}

    def dominant_color(
        _self: ArtworkPixmapProvider,
        artwork_id: int,
        _size: int,
        _dpr: float,
    ) -> tuple[int, int, int] | None:
        return colors.get(artwork_id)

    monkeypatch.setattr(
        ArtworkPixmapProvider,
        "dominant_color",
        dominant_color,
    )
    page = _page(context)
    try:
        grid, panel, tabs = _open(page)
        expansion = page.findChild(InlineAlbumExpansion)
        assert expansion is not None
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "Season 1",
            "Season 2",
            "Season 10",
        ]
        summary = grid.model().index(0, 0).data(CollectionRole.SUMMARY)
        assert (
            isinstance(summary, CollectionSummary)
            and summary.representative_artwork_id == 101
        )
        assert _ids(panel) == [2, 3, 4] and panel.artwork_id == 103
        assert panel.track_view.model().columnCount() == 1
        original = panel.grab().toImage().pixelColor(2, panel.height() - 2)
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
        QTest.qWait(50)
        assert panel.isVisible() and expansion.expanded_index == grid.model().index(
            0, 0
        )
        assert _ids(panel) == [5, 6] and panel.artwork_id == 105
        assert panel.grab().toImage().pixelColor(2, panel.height() - 2) != original
        tabs.setFocus()
        QTest.keyClick(tabs, Qt.Key.Key_Right)
        assert _ids(panel) == [1] and panel.artwork_id == 101
        assert panel.isVisible()
        # Resizing never turns episodes into side-by-side Album track columns.
        for width in (600, 1500):
            page.resize(width, 850)
            QTest.qWait(60)
            assert panel.track_view.model().columnCount() == 1
            assert panel.track_view.geometry().right() < panel.width()
            assert tabs.geometry().right() < panel.width()
        text = (
            panel.track_view.model()
            .index(0, 0)
            .data(Qt.ItemDataRole.AccessibleTextRole)
        )
        assert "Episode 1" in text and "43:00" in text and "★" not in text
        assert not any(
            button.text() == "More" for button in panel.findChildren(QToolButton)
        )
        QTest.keyClick(tabs, Qt.Key.Key_Escape)
        _finish_expansion(page)
        assert not panel.isVisible()
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize("action", ("Play", "PlayNext", "Queue"))
def test_season_actions_drag_and_activation_use_only_visible_episodes(
    context: AppContext,
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.settings.set_global(
        LIBRARY_DOUBLE_CLICK_SHORTCUT, LibraryDoubleClickShortcut.PLAY_NOW.value
    )
    window = MainWindow(context, auto_discover=False)
    drags: list[QDrag] = []

    def record_drag(drag: QDrag, _action: Qt.DropAction) -> Qt.DropAction:
        drags.append(drag)
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(QDrag, "exec", record_drag)
    try:
        window.resize(1500, 950)
        window.show()
        bar = window.findChild(CompactTopBar)
        page = window.findChild(CollectionPage, "tv-showsPage")
        actions = window.findChild(TrackActions)
        assert bar is not None and page is not None and actions is not None
        bar.pageRequested.emit(PageId.TV_SHOWS.value)
        QTest.qWait(80)
        grid, panel, tabs = _open(page)
        assert {track.track_id for track in actions.selection(grid).tracks} == {
            1,
            2,
            3,
            4,
            5,
            6,
        }
        tabs.setCurrentIndex(1)
        button = panel.findChild(QToolButton, f"inlineAlbum{action}")
        assert button is not None
        playback = context.playback_controller
        playback.play_now((context.track_model.tracks[-1],))
        button.click()
        if action == "Play":
            assert (
                playback.current_track is not None
                and playback.current_track.track_id == 5
            )
            assert [entry.track.track_id for entry in playback.queue_model.entries] == [
                6
            ]
        else:
            assert [entry.track.track_id for entry in playback.queue_model.entries] == [
                5,
                6,
            ]
        view = panel.track_view
        view.setCurrentIndex(view.model().index(0, 0))
        view.selectAll()
        view.startDrag(Qt.DropAction.CopyAction)
        dragged = dropped_tracks(drags[0].mimeData(), context.library_workspace)
        assert dragged is not None
        assert [track.track_id for track in dragged] == [5, 6]
        tabs.setCurrentIndex(0)
        assert not panel.selected_tracks()
        view.doubleClicked.emit(view.model().index(1, 0))
        assert (
            playback.current_track is not None and playback.current_track.track_id == 3
        )
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize(
    "mode", (IPodLibraryViewMode.SPLIT_TABLE, IPodLibraryViewMode.WHOLE_PAGE_TABLE)
)
def test_table_modes_keep_all_show_episodes_and_single_cover(
    context: AppContext, mode: IPodLibraryViewMode
) -> None:
    context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
    page = _page(context)
    try:
        grid = page.findChild(CollectionGridView)
        table = page.findChild(TrackTable)
        assert grid is not None and table is not None
        grid.setCurrentIndex(grid.model().index(0, 0))
        _click_show(grid)
        APPLICATION.processEvents()
        assert table.isVisible() and set(_ids(table)) == {1, 2, 3, 4, 5, 6}
        if mode is IPodLibraryViewMode.WHOLE_PAGE_TABLE:
            detail = page.findChild(CollectionDetailPage)
            assert detail is not None and detail.isVisible()
            cover = detail.findChild(ArtworkView)
            assert cover is not None and cover.accessibleName() == "Album artwork"
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
        )
        _, panel, tabs = _open(page)
        tabs.setCurrentIndex(1)
        context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
        content = page.findChild(LibraryContent)
        assert content is not None
        if mode is IPodLibraryViewMode.WHOLE_PAGE_TABLE:
            _click_show(grid)
        assert not panel.isVisible() and set(_ids(table)) == {1, 2, 3, 4, 5, 6}
    finally:
        page.close()
        page.deleteLater()


def test_missing_metadata_updates_and_reset_keep_valid_season_context(
    context: AppContext,
) -> None:
    context.track_model.reset_tracks(tuple(_episode(i, 0, i) for i in range(1, 1001)))
    page = _page(context)
    try:
        _, panel, tabs = _open(page)
        assert tabs.tabText(0) == "Unknown season" and panel.artwork_id == 0
        assert len(_ids(panel)) == 1000
        assert len(panel.findChildren(QLabel)) == 2
        assert panel.track_view.verticalScrollBar().maximum() > 0
        tracks = context.track_model.tracks
        context.track_model.replace_tracks((*tracks, _episode(1001, 2, 1, 12)))
        APPLICATION.processEvents()
        assert tabs.count() == 2 and tabs.currentIndex() == 0
        tabs.setCurrentIndex(1)
        context.track_model.replace_tracks(
            (*tracks, replace(_episode(1001, 2, 1, 13), title="Updated"))
        )
        APPLICATION.processEvents()
        assert panel.isVisible() and _ids(panel) == [1001] and panel.artwork_id == 13
        context.track_model.replace_tracks(tracks)
        APPLICATION.processEvents()
        assert (
            tabs.count() == 1 and tabs.currentIndex() == 0 and len(_ids(panel)) == 1000
        )
        context.track_model.reset_tracks(())
        APPLICATION.processEvents()
        assert not panel.isVisible()
    finally:
        page.close()
        page.deleteLater()
