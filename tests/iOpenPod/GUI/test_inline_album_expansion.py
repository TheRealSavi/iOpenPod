"""The iTunes 11 preference reveals Album contents inside the existing grid."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    IPodLibraryViewMode,
)
from iOpenPod.app.models.album_list_model import AlbumRole
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.inline_album_expansion import InlineAlbumExpansion
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.library_content import LibraryContent
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import Track


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    context.track_model.reset_tracks(
        tuple(
            Track(
                album * 10 + number,
                f"Song {number}",
                "Artist",
                f"Album {album:03}",
                183_000,
                track_number=number,
                rating=number * 20,
            )
            for album in range(100)
            for number in (2, 1, 3)
        )
    )
    yield context
    context.shutdown()


def _page(context: AppContext) -> LibraryPage:
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = LibraryPage(
        context.track_model,
        context.album_model,
        context.settings,
        context.theme_manager,
        provider,
    )
    provider.setParent(page)
    page.resize(1100, 820)
    page.show()
    QTest.qWait(50)
    return page


@pytest.mark.parametrize("saved", (False, True))
def test_expand_switch_close_resize_and_restore_modes(
    context: AppContext, saved: bool
) -> None:
    if saved:
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
        )
    page = _page(context)
    grid = page.findChild(AlbumGridView)
    panel = page.findChild(InlineAlbumPanel)
    table = page.findChild(TrackTable)
    content = page.findChild(LibraryContent)
    assert (
        grid is not None
        and panel is not None
        and table is not None
        and content is not None
    )
    if not saved:
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
        )
        QTest.qWait(50)
    assert content.inline_albums and grid.isVisible() and not table.isVisible()
    index = grid.model().index(0, 0)
    later = grid.model().index(8, 0)
    before = grid.visualRect(later).top()
    QTest.mouseClick(
        grid.viewport(), Qt.MouseButton.LeftButton, pos=grid.visualRect(index).center()
    )
    QTest.qWait(280)
    assert panel.isVisible()
    assert grid.visualRect(later).top() > before + 150
    assert (
        panel.mapTo(grid.viewport(), panel.rect().topLeft()).y()
        > grid.visualRect(index).top()
    )
    track_model = panel.track_view.model()
    assert [
        track_id
        for column in range(track_model.columnCount())
        for row in range(track_model.rowCount())
        if (track_id := track_model.index(row, column).data(TrackRole.TRACK_ID))
        is not None
    ] == [1, 2, 3]
    assert grid.model().index(0, 0).data(AlbumRole.TITLE) == "Album 000"
    page.resize(760, 820)
    QTest.qWait(100)
    assert panel.isVisible() and panel.width() == grid.viewport().width()
    QTest.keyClick(grid, Qt.Key.Key_Escape)
    QTest.qWait(280)
    assert not panel.isVisible()
    grid.setCurrentIndex(index)
    QTest.keyClick(grid, Qt.Key.Key_Return)
    QTest.qWait(280)
    assert panel.isVisible()
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.SPLIT_TABLE.value
    )
    QTest.qWait(50)
    assert grid.isVisible() and table.isVisible() and not panel.isVisible()
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    QTest.qWait(50)
    assert content.whole_page_table and grid.isVisible() and not table.isVisible()
    page.close()


def test_filter_and_library_reset_dismiss_stale_album(context: AppContext) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    grid = page.findChild(AlbumGridView)
    panel = page.findChild(InlineAlbumPanel)
    assert grid is not None and panel is not None
    grid.clicked.emit(grid.model().index(0, 0))
    QTest.qWait(280)
    assert panel.isVisible()
    context.track_model.reset_tracks(())
    APPLICATION.processEvents()
    assert not panel.isVisible() and grid.model().rowCount() == 0
    page.close()


def test_deep_scrolled_album_stays_laid_out_and_reveals_visible_contents(
    context: AppContext,
) -> None:
    from PySide6.QtWidgets import QWidget

    context.track_model.reset_tracks(
        tuple(
            Track(number + 1, "Song", "Artist", f"Album {number:03}", 183_000)
            for number in range(500)
        )
    )
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        clip = page.findChild(QWidget, "inlineAlbumReveal")
        assert grid is not None and panel is not None
        assert animation is not None and clip is not None
        index = grid.model().index(300, 0)
        grid.scrollTo(index)
        QTest.qWait(80)
        position_before = grid.verticalScrollBar().value()
        assert position_before > grid.viewport().height()
        frames: list[tuple[bool, bool]] = []

        def record_frame(value: object) -> None:
            if isinstance(value, (int, float)) and value > 0:
                frames.append((grid.visualRect(index).isValid(), clip.isVisible()))

        animation.valueChanged.connect(record_frame)
        grid.clicked.emit(index)
        # The zero-height first frame must not expose old/default clip geometry.
        assert not clip.isVisible()
        QTest.qWait(300)

        assert frames and all(valid and visible for valid, visible in frames)
        assert panel.isVisible()
        panel_top = panel.mapTo(grid.viewport(), QPoint()).y()
        assert 0 <= panel_top < grid.viewport().height() - 120
        assert grid.verticalScrollBar().value() >= position_before
        assert grid.visualRect(index).top() >= 0
        assert grid.model().index(300, 0).data(AlbumRole.TITLE) == "Album 300"
    finally:
        page.close()


def test_resizing_during_collapse_finishes_closed(context: AppContext) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        expansion = page.findChild(InlineAlbumExpansion)
        assert grid is not None and panel is not None and expansion is not None
        grid.clicked.emit(grid.model().index(0, 0))
        QTest.qWait(280)
        assert panel.isVisible()

        panel.closeRequested.emit()
        QTest.qWait(25)
        page.resize(760, 820)
        QTest.qWait(280)

        assert not panel.isVisible()
        assert not expansion.expanded_index.isValid()
        # A later resize must not resurrect the closed Album.
        page.resize(1050, 820)
        QTest.qWait(50)
        assert not panel.isVisible()
    finally:
        page.close()


def test_card_click_toggles_switches_and_filter_dismisses_album(
    context: AppContext,
) -> None:
    from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
    from iOpenPod.GUI.widgets.search_field import SearchField

    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        expansion = page.findChild(InlineAlbumExpansion)
        toolbar = page.findChild(LibraryToolbar)
        assert grid is not None and panel is not None and expansion is not None
        assert toolbar is not None
        search = toolbar.findChild(SearchField)
        assert search is not None

        def click_card(row: int) -> None:
            index = grid.model().index(row, 0)
            # visualRect includes the detail band, so target the artwork itself.
            QTest.mouseClick(
                grid.viewport(),
                Qt.MouseButton.LeftButton,
                pos=grid.visualRect(index).topLeft() + QPoint(60, 60),
            )
            QTest.qWait(280)

        click_card(0)
        assert panel.isVisible()
        click_card(0)
        assert not panel.isVisible() and not expansion.expanded_index.isValid()
        click_card(0)
        click_card(1)
        assert panel.isVisible()
        assert expansion.expanded_index.data(AlbumRole.TITLE) == "Album 001"
        model = panel.track_view.model()
        assert {
            track_id
            for column in range(model.columnCount())
            for row in range(model.rowCount())
            if (track_id := model.index(row, column).data(TrackRole.TRACK_ID))
            is not None
        } == {11, 12, 13}

        search.setText("Album 090")
        QTest.qWait(280)
        assert not panel.isVisible() and not expansion.expanded_index.isValid()
        assert grid.model().rowCount() == 1
        assert grid.model().index(0, 0).data(AlbumRole.TITLE) == "Album 090"
    finally:
        page.close()


def test_inline_animation_and_collapse_keep_complete_batches(
    context: AppContext,
) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        assert grid is not None and panel is not None and animation is not None
        columns = next(
            row
            for row in range(grid.model().rowCount())
            if grid.visualRect(grid.model().index(row, 0)).top() > 0
        )
        assert 64 % columns != 0
        batch_sizes: list[int] = []

        def record_batch_size(_value: object) -> None:
            batch_sizes.append(grid.batchSize())

        animation.valueChanged.connect(record_batch_size)
        grid.clicked.emit(grid.model().index(0, 0))
        QTest.qWait(280)
        assert batch_sizes and all(size % columns == 0 for size in batch_sizes)
        assert grid.batchSize() % columns == 0
        panel.closeRequested.emit()
        QTest.qWait(280)
        assert grid.batchSize() % columns == 0
        # A fresh native layout after restoring the normal budget must not leave
        # a partial row at the first or subsequent batch boundary.
        grid.doItemsLayout()
        QTest.qWait(80)
        rects = [
            grid.visualRect(grid.model().index(row, 0))
            for row in range(grid.model().rowCount())
        ]
        cell_height = rects[0].height()
        for row, rect in enumerate(rects):
            assert rect.left() == rects[row % columns].left()
            assert rect.top() == (row // columns) * cell_height
    finally:
        page.close()


@pytest.mark.parametrize("album_row", (0, 300))
def test_every_opening_frame_keeps_panel_below_the_selected_card(
    context: AppContext, album_row: int
) -> None:
    """The reveal must never paint over the card while batched layout catches up."""
    context.track_model.reset_tracks(
        tuple(
            Track(number + 1, "Song", "Artist", f"Album {number:03}", 183_000)
            for number in range(500)
        )
    )
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        from PySide6.QtWidgets import QWidget

        grid = page.findChild(AlbumGridView)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        clip = page.findChild(QWidget, "inlineAlbumReveal")
        assert grid is not None and animation is not None and clip is not None
        index = grid.model().index(album_row, 0)
        grid.scrollTo(index)
        QTest.qWait(50)
        card_height = grid.visualRect(index).height()
        frames: list[tuple[bool, int, int, int, int]] = []

        def record_frame(value: object) -> None:
            if isinstance(value, int) and value > 0:
                card = grid.visualRect(index)
                reserved = card.height() - card_height
                frames.append(
                    (
                        clip.isVisible(),
                        clip.y(),
                        card.top() + card_height,
                        clip.height(),
                        reserved,
                    )
                )

        animation.valueChanged.connect(record_frame)
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).topLeft() + QPoint(60, 60),
        )
        animation.pause()
        for ms in range(16, animation.duration() + 16, 16):
            animation.setCurrentTime(min(ms, animation.duration()))
            APPLICATION.processEvents()
        assert frames
        assert all(
            (visible and top == expected_top and height == reserved)
            if reserved > 0
            else not visible
            for visible, top, expected_top, height, reserved in frames
        ), frames
    finally:
        page.close()


@pytest.mark.parametrize("album_row", (0, 1))
def test_reopening_album_never_flashes_full_panel_before_reveal(
    context: AppContext,
    album_row: int,
) -> None:
    from PySide6.QtWidgets import QWidget

    context.track_model.reset_tracks(
        tuple(
            Track(number + 1, "Song", "Artist", f"Album {number:03}", 183_000)
            for number in range(6)
        )
    )
    page = _page(context)
    # Keep both card rows and the panel visible without a scrollbar resize.
    page.resize(1100, 1200)
    APPLICATION.processEvents()
    try:
        grid = page.findChild(AlbumGridView)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        clip = page.findChild(QWidget, "inlineAlbumReveal")
        assert grid is not None and animation is not None and clip is not None
        index = grid.model().index(0, 0)

        def click_card() -> None:
            QTest.mouseClick(
                grid.viewport(),
                Qt.MouseButton.LeftButton,
                pos=grid.visualRect(index).topLeft() + QPoint(60, 60),
            )

        click_card()
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        assert clip.isVisible()
        click_card()
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        assert not clip.isVisible()

        index = grid.model().index(album_row, 0)
        click_card()
        animation.pause()
        heights = [clip.height() if clip.isVisible() else 0]
        for ms in range(16, animation.duration() + 16, 16):
            animation.setCurrentTime(min(ms, animation.duration()))
            APPLICATION.processEvents()
            heights.append(clip.height() if clip.isVisible() else 0)
        assert heights[0] == 0, heights
        assert heights == sorted(heights), heights
        assert heights[-1] > 0
    finally:
        page.close()


def test_reversing_album_reveal_keeps_current_height(context: AppContext) -> None:
    from PySide6.QtWidgets import QWidget

    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        clip = page.findChild(QWidget, "inlineAlbumReveal")
        assert grid is not None and animation is not None and clip is not None
        index = grid.model().index(0, 0)
        grid.clicked.emit(index)
        animation.pause()
        animation.setCurrentTime(animation.duration() // 2)
        APPLICATION.processEvents()
        opening_height = clip.height()
        assert clip.isVisible() and opening_height > 0

        grid.clicked.emit(index)
        animation.pause()
        APPLICATION.processEvents()
        assert clip.isVisible() and clip.height() == opening_height
        animation.setCurrentTime(animation.duration() // 2)
        APPLICATION.processEvents()
        closing_height = clip.height()
        assert 0 < closing_height < opening_height

        # Keyboard activation opens the current Album even during collapse.
        grid.setCurrentIndex(index)
        QTest.keyClick(grid, Qt.Key.Key_Return)
        animation.pause()
        APPLICATION.processEvents()
        assert clip.isVisible() and clip.height() == closing_height
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        assert clip.height() > opening_height
    finally:
        page.close()


class _GridHoverEvents(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.events: list[QEvent.Type] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self.events.append(event.type())
        return False


@pytest.mark.parametrize(
    "area",
    (
        "background",
        "title",
        "artist",
        "artwork",
        "empty_table",
        "empty_cell",
        "pointer",
    ),
)
@pytest.mark.parametrize(
    "interaction", ("hover", "click", "double_click", "context_menu")
)
def test_panel_mouse_input_does_not_reach_album_cards(
    context: AppContext, area: str, interaction: str
) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        expansion = page.findChild(InlineAlbumExpansion)
        assert grid is not None and panel is not None and expansion is not None
        index = grid.model().index(0, 0)
        card_point = grid.visualRect(index).topLeft() + QPoint(60, 60)
        window = page.windowHandle()
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).topLeft() + QPoint(60, 60),
        )
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        assert animation is not None
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        QTest.mouseMove(window, grid.viewport().mapTo(page, card_point))
        view = panel.track_view
        assert view.model().columnCount() == 2
        if area in ("title", "artist"):
            labels = panel.findChildren(
                QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly
            )
            label = next(
                label
                for label in labels
                if label.text() == ("Album 000" if area == "title" else "Artist")
            )
            point = label.mapTo(panel, label.rect().center())
        elif area == "artwork":
            cover = panel.findChild(ArtworkView)
            assert cover is not None
            point = cover.mapTo(panel, cover.rect().center())
        elif area == "empty_table":
            point = view.viewport().mapTo(
                panel, view.viewport().rect().bottomLeft() + QPoint(100, -10)
            )
        elif area == "empty_cell":
            blank = view.model().index(1, 1)
            assert blank.data(TrackRole.TRACK) is None
            point = view.viewport().mapTo(panel, view.visualRect(blank).center())
        else:
            point = QPoint(
                panel.width() // 2, 5 if area == "pointer" else panel.height() - 5
            )
        # Deliver input to the child at this screen position, like the real window
        # system, rather than sending it directly to the grid's viewport.
        target = panel.childAt(point) or panel
        local = target.mapFrom(panel, point)
        selected = grid.selectionModel().selectedIndexes()
        grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        menu = QSignalSpy(grid.customContextMenuRequested)
        hovered = QSignalSpy(grid.entered)
        hover_events = _GridHoverEvents(grid)
        grid.viewport().installEventFilter(hover_events)
        pressed = QSignalSpy(grid.pressed)
        clicked = QSignalSpy(grid.clicked)
        double_clicked = QSignalSpy(grid.doubleClicked)
        if interaction == "hover":
            QTest.mouseMove(window, panel.mapTo(page, point))
        elif interaction == "click":
            QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=local)
        elif interaction == "double_click":
            QTest.mouseDClick(target, Qt.MouseButton.LeftButton, pos=local)
            QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=local)
        else:
            APPLICATION.sendEvent(
                target,
                QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    local,
                    target.mapToGlobal(local),
                ),
            )
        APPLICATION.processEvents()
        assert not hover_events.events
        assert menu.count() == 0
        assert hovered.count() == 0
        assert pressed.count() == 0
        assert clicked.count() == 0
        assert double_clicked.count() == 0
        assert grid.selectionModel().selectedIndexes() == selected
        assert expansion.expanded_index == index
        if interaction == "hover":
            assert target.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        page.close()


@pytest.mark.parametrize("pixels", (0, 17))
def test_wheel_over_panel_background_still_scrolls_the_grid(
    context: AppContext,
    pixels: int,
) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        assert grid is not None and panel is not None
        grid.clicked.emit(grid.model().index(0, 0))
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        assert animation is not None
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        point = QPoint(panel.width() // 2, panel.height() - 5)
        assert panel.childAt(point) is None
        before = grid.verticalScrollBar().value()
        window = page.windowHandle()
        QTest.wheelEvent(
            window, panel.mapTo(page, point), QPoint(0, -120), QPoint(0, -pixels)
        )
        QTest.qWait(200)
        distance = grid.verticalScrollBar().value() - before
        assert distance == pixels if pixels else 0 < distance <= 144
    finally:
        page.close()


def test_wheel_over_scrollable_tracks_stays_in_the_panel(context: AppContext) -> None:
    context.track_model.reset_tracks(
        tuple(
            Track(
                album * 100 + number,
                f"Song {number}",
                "Artist",
                f"Album {album:03}",
                183_000,
            )
            for album in range(10)
            for number in range(1, 60)
        )
    )
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    page = _page(context)
    try:
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        animation = page.findChild(QVariantAnimation, "inlineAlbumAnimation")
        window = page.windowHandle()
        assert grid is not None and panel is not None and animation is not None
        grid.clicked.emit(grid.model().index(0, 0))
        animation.setCurrentTime(animation.duration())
        APPLICATION.processEvents()
        view = panel.track_view
        assert view.verticalScrollBar().maximum() > 0
        before = grid.verticalScrollBar().value()
        QTest.wheelEvent(
            window, view.viewport().mapTo(page, QPoint(50, 50)), QPoint(0, -120)
        )
        QTest.qWait(200)
        assert view.verticalScrollBar().value() > 0
        assert grid.verticalScrollBar().value() == before
    finally:
        page.close()
