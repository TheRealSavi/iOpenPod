"""The iPod Tracks scope defaults to music and can expose every Track."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.track_page import TrackPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iOpenPod.GUI.widgets.track_media_switch import TrackMediaSwitch
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind, MediaType, Track


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    context.track_model.replace_tracks(
        tuple(
            Track(
                index,
                f"Shared {kind.value}",
                "Artist",
                "Album",
                1000,
                media_types=(kind,),
            )
            for index, kind in enumerate(
                (
                    MediaType.AUDIO,
                    MediaType.PODCAST,
                    MediaType.VIDEO_PODCAST,
                    MediaType.AUDIOBOOK,
                    MediaType.VIDEO,
                    MediaType.TV_SHOW,
                    MediaType.MUSIC_VIDEO,
                ),
                1,
            )
        )
    )
    yield context
    context.shutdown()


def _page(
    context: AppContext,
    *,
    show_media_switch: bool = True,
    media_kinds: tuple[MediaKind, ...] | None = None,
) -> TrackPage:
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = TrackPage(
        context.track_model,
        context.settings,
        context.theme_manager,
        provider,
        PageId.TRACKS,
        "media-switch-test",
        media_kinds,
        show_media_switch=show_media_switch,
    )
    provider.setParent(page)
    page.resize(1000, 600)
    page.show()
    APPLICATION.processEvents()
    return page


def test_music_default_and_all_media_switch_preserve_search_and_sort(
    context: AppContext,
) -> None:
    page = _page(context)
    try:
        music = page.findChild(IconButton, "tracksMusicOnly")
        all_media = page.findChild(IconButton, "tracksAllMedia")
        table = page.findChild(TrackTable)
        search = page.findChild(SearchField)
        toolbar = page.findChild(LibraryToolbar)
        switch = page.findChild(TrackMediaSwitch)
        assert music and all_media and table and search and toolbar and switch
        model = table.model()
        assert music.isChecked() and not all_media.isChecked()
        assert model.rowCount() == 1
        assert model.index(0, 0).data(TrackRole.TRACK_ID) == 1
        assert switch.geometry().right() < search.geometry().left()
        assert switch.geometry().top() > toolbar.contentsRect().top()

        search.setText("Shared")
        QTest.qWait(220)
        table.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
        all_media.setFocus()
        QTest.keyClick(all_media, Qt.Key.Key_Space)
        assert all_media.isChecked() and not music.isChecked()
        assert model.rowCount() == 7
        assert search.text() == "Shared"
        titles = [model.index(row, TrackColumn.TITLE).data() for row in range(7)]
        assert titles == sorted(titles, reverse=True)

        search.setText("podcast")
        QTest.qWait(220)
        assert model.rowCount() == 2
        music.click()
        assert model.rowCount() == 0
        assert search.text() == "podcast"
        all_media.click()
        assert model.rowCount() == 2
        APPLICATION.sendEvent(switch, QEvent(QEvent.Type.LanguageChange))
        assert all_media.isChecked()
        assert all_media.accessibleName() == "All media"
        assert music.toolTip() == "Show music only"
        all_media.click()
        assert all_media.isChecked()

        context.track_model.replace_tracks(context.track_model.tracks[:2])
        assert model.rowCount() == 1
        music.click()
        search.clear()
        QTest.qWait(220)
        assert model.rowCount() == 1
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_diagnostic_reveals_non_music_and_clears_search(context: AppContext) -> None:
    page = _page(context)
    try:
        search = page.findChild(SearchField)
        all_media = page.findChild(IconButton, "tracksAllMedia")
        table = page.findChild(TrackTable)
        assert search and all_media and table
        search.setText("does not match")
        QTest.qWait(220)
        assert table.model().rowCount() == 0
        assert page.select_track(3)
        assert all_media.isChecked()
        assert search.text() == ""
        assert table.currentIndex().data(TrackRole.TRACK_ID) == 3
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("media_kinds", [None, (MediaKind.AUDIOBOOK,)])
def test_host_and_category_pages_keep_their_scope(
    context: AppContext, media_kinds: tuple[MediaKind, ...] | None
) -> None:
    page = _page(context, show_media_switch=False, media_kinds=media_kinds)
    try:
        assert page.findChild(TrackMediaSwitch) is None
        table = page.findChild(TrackTable)
        assert table is not None
        assert table.model().rowCount() == (7 if media_kinds is None else 1)
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)
