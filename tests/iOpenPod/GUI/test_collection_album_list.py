"""iTunes 11 Artist/Genre sections preserve Track identity and action scope."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QListView, QScrollArea, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.models.collection_list_model import CollectionRole
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.collection_album_list import CollectionAlbumList
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, Track


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    context.track_model.reset_tracks(
        tuple(
            Track(
                n,
                f"Song {n}",
                "Artist",
                "First" if n < 6 else "Second",
                180_000,
                genre="Jazz" if n in (4, 5) else "Rock",
                year=2001 if n < 6 else 2003,
                track_number=n if n < 6 else n - 5,
                rating=80,
                album_artist="Album Artist",
            )
            for n in range(1, 9)
        )
    )
    yield context
    context.shutdown()


def _page(context: AppContext, page_id: PageId) -> CollectionPage:
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = CollectionPage(
        context.track_model,
        context.artist_model if page_id is PageId.ARTISTS else context.genre_model,
        context.settings,
        context.theme_manager,
        provider,
        page_id=page_id,
        table_id=f"{page_id.value}-test",
        albums=context.album_model,
    )
    provider.setParent(page)
    page.resize(1280, 700)
    page.show()
    APPLICATION.processEvents()
    return page


def _sections(page: CollectionPage) -> list[InlineAlbumPanel]:
    return [panel for panel in page.findChildren(InlineAlbumPanel) if panel.isVisible()]


def _ids(panel: InlineAlbumPanel) -> list[int]:
    model = panel.track_view.model()
    return [
        value
        for column in range(model.columnCount())
        for row in range(model.rowCount())
        if isinstance(value := model.index(row, column).data(TrackRole.TRACK_ID), int)
    ]


@pytest.mark.parametrize("page_id", [PageId.ARTISTS, PageId.GENRES])
def test_itunes_list_only_sections_and_collection_actions(
    context: AppContext, page_id: PageId
) -> None:
    page = _page(context, page_id)
    try:
        view = page.findChild(QListView, f"{page_id.value}CollectionList")
        assert view is not None and view.isVisible()
        if page_id is PageId.GENRES:
            index = next(
                view.model().index(row, 0)
                for row in range(view.model().rowCount())
                if view.model().index(row, 0).data(CollectionRole.SUMMARY).title
                == "Rock"
            )
            view.setCurrentIndex(index)
            APPLICATION.processEvents()
        switch = page.findChild(QWidget, f"{page_id.value}ViewModes")
        assert switch is not None and switch.isHidden()
        page.set_view_mode("grid")
        assert view.isVisible()
        table = page.findChild(TrackTable)
        assert table is not None and not table.isVisible()
        sections = _sections(page)
        assert len(sections) == 2
        expected = (
            list(range(1, 9)) if page_id is PageId.ARTISTS else [1, 2, 3, 6, 7, 8]
        )
        assert [
            track_id for section in sections for track_id in _ids(section)
        ] == expected
        for section in sections:
            assert section.track_view.model().columnCount() == 2
            assert "★" not in str(
                section.track_view.model()
                .index(0, 0)
                .data(Qt.ItemDataRole.AccessibleTextRole)
            )
            cover = section.findChild(ArtworkView)
            assert (
                cover is not None and cover.geometry().right() < section.track_view.x()
            )
            assert cover.width() == (64 if page_id is PageId.GENRES else 168)
            assert section.track_view.verticalScrollBar().maximum() == 0
            year = section.findChild(QLabel, "albumSectionYear")
            assert year is not None and year.text() in (
                "2001",
                "2003",
            )
            if page_id is PageId.GENRES:
                assert any(
                    label.text() == "by Album Artist"
                    for label in section.findChildren(QLabel)
                )
        for name, signal in (
            ("collectionPlay", page.playRequested),
            ("collectionPlayNext", page.playNextRequested),
            ("collectionQueue", page.queueRequested),
        ):
            spy = QSignalSpy(signal)
            button = page.findChild(IconButton, name)
            assert button is not None and button.isEnabled()
            button.click()
            assert spy.count() == 1
            assert [track.track_id for track in spy.at(0)[0]] == expected
    finally:
        page.close()
        page.deleteLater()


def test_switching_modes_preserves_collection_and_restores_browser_choice(
    context: AppContext,
) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.SPLIT_TABLE.value
    )
    page = _page(context, PageId.ARTISTS)
    try:
        page.set_view_mode("list")
        view = page.findChild(QListView, "artistsCollectionList")
        assert view is not None
        view.setCurrentIndex(view.model().index(0, 0))
        key = view.currentIndex().data(CollectionRole.KEY)
        for mode in (
            IPodLibraryViewMode.ITUNES_11,
            IPodLibraryViewMode.WHOLE_PAGE_TABLE,
            IPodLibraryViewMode.ITUNES_11,
            IPodLibraryViewMode.SPLIT_TABLE,
        ):
            context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
            APPLICATION.processEvents()
            assert view.currentIndex().data(CollectionRole.KEY) == key
            switch = page.findChild(QWidget, "artistsViewModes")
            assert switch is not None and switch.isHidden() == (
                mode is IPodLibraryViewMode.ITUNES_11
            )
        assert view.isVisible()
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize("page_id", [PageId.ARTISTS, PageId.GENRES])
@pytest.mark.parametrize("action", ["Play", "PlayNext", "Queue"])
def test_collection_actions_and_materialized_track_cells_use_playback(
    context: AppContext, page_id: PageId, action: str
) -> None:
    tracks = context.track_model.tracks
    outside = Track(20, "Current", "Other", "Other", 1000)
    pending = Track(21, "Pending", "Other", "Other", 1000)
    context.library_workspace.load(LibrarySnapshot((*tracks, outside, pending)))
    context.settings.set_global(
        LIBRARY_DOUBLE_CLICK_SHORTCUT, LibraryDoubleClickShortcut.PLAY_NOW.value
    )
    window = MainWindow(context, auto_discover=False)
    try:
        window.resize(1280, 900)
        window.show()
        bar = window.findChild(CompactTopBar)
        page = window.findChild(CollectionPage, f"{page_id.value}Page")
        assert bar is not None and page is not None
        bar.pageRequested.emit(page_id.value)
        APPLICATION.processEvents()
        view = page.findChild(QListView, f"{page_id.value}CollectionList")
        assert view is not None
        title = "Artist" if page_id is PageId.ARTISTS else "Rock"
        view.setCurrentIndex(
            next(
                view.model().index(row, 0)
                for row in range(view.model().rowCount())
                if view.model().index(row, 0).data(CollectionRole.SUMMARY).title
                == title
            )
        )
        APPLICATION.processEvents()
        expected = tuple(
            track
            for track in tracks
            if page_id is PageId.ARTISTS or track.genre == "Rock"
        )
        playback = context.playback_controller
        playback.play_now((outside, pending))
        button = page.findChild(IconButton, f"collection{action}")
        assert button is not None and button.isEnabled()
        button.click()
        if action == "Play":
            assert playback.current_track == expected[0]
            queued = (*expected[1:], pending)
        else:
            assert playback.current_track == outside
            queued = (
                (*expected, pending) if action == "PlayNext" else (pending, *expected)
            )
        assert tuple(entry.track for entry in playback.queue_model.entries) == queued

        # These cells are created after the shell: their normal Track actions
        # must be installed as each visible section is materialized.
        section = _sections(page)[0]
        cells = section.track_view
        right = cells.model().index(0, 1)
        target = context.library_workspace.track(right.data(TrackRole.TRACK_ID))
        cells.doubleClicked.emit(right)
        assert playback.current_track == target
        first = cells.model().index(0, 0)
        cells.setCurrentIndex(first)
        QTest.keyClick(cells, Qt.Key.Key_Return)
        assert playback.current_track == expected[0]
    finally:
        window.close()
        window.deleteLater()


def test_many_albums_materialize_only_visible_sections_and_refresh_after_edit(
    context: AppContext,
) -> None:
    tracks = tuple(
        Track(n, f"Song {n}", "Artist", f"Album {n:03d}", 1000) for n in range(300)
    )
    context.track_model.reset_tracks(tracks)
    page = _page(context, PageId.ARTISTS)
    try:
        album_list = page.findChild(CollectionAlbumList)
        assert album_list is not None
        assert len(album_list.findChildren(InlineAlbumPanel)) < 10
        scroll = album_list.findChild(QScrollArea)
        assert scroll is not None and scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        APPLICATION.processEvents()
        assert any(299 in _ids(panel) for panel in _sections(page))
        context.track_model.reset_tracks(())
        APPLICATION.processEvents()
        APPLICATION.processEvents()
        assert not _sections(page)
        play = page.findChild(IconButton, "collectionPlay")
        assert play is not None and not play.isEnabled()
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize(
    ("page_id", "title"),
    [(PageId.ARTISTS, "Unknown Artist"), (PageId.GENRES, "Unknown Genre")],
)
def test_missing_metadata_keeps_a_named_collection_header(
    context: AppContext, page_id: PageId, title: str
) -> None:
    context.track_model.reset_tracks((Track(1, "Song", "", "Album", 1000),))
    page = _page(context, page_id)
    try:
        heading = page.findChild(QLabel, "collectionAlbumTitle")
        assert heading is not None and heading.text() == title
        assert len(_sections(page)) == 1
    finally:
        page.close()
        page.deleteLater()


def test_artist_sections_include_matching_tracks_from_a_shared_album(
    context: AppContext,
) -> None:
    context.track_model.reset_tracks(
        (
            Track(1, "Main song", "Main Artist", "Album", 1000, album_artist="Band"),
            Track(2, "Guest song", "Guest Artist", "Album", 1000, album_artist="Band"),
        )
    )
    page = _page(context, PageId.ARTISTS)
    try:
        heading = page.findChild(QLabel, "collectionAlbumTitle")
        assert heading is not None and heading.text() == "Guest Artist"
        sections = _sections(page)
        assert len(sections) == 1
        assert _ids(sections[0]) == [2]
    finally:
        page.close()
        page.deleteLater()
