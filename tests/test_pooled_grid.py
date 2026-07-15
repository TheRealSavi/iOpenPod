from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QScrollArea

from iopenpod.gui.styles import Metrics
from iopenpod.gui.widgets.gridItem import GridItem
from iopenpod.gui.widgets.pooledGrid import GridItemModel, PooledGridView


def _mount_grid(qtbot, *, checkable: bool = False) -> PooledGridView:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = PooledGridView(checkable=checkable)
    scroll.setWidget(grid)
    grid.attachScrollArea(scroll)
    qtbot.addWidget(scroll)
    scroll.resize(920, 620)
    scroll.show()
    return grid


def _solid_pixmap(rgb: tuple[int, int, int]) -> QPixmap:
    pixmap = QPixmap(48, 48)
    pixmap.fill(QColor(*rgb))
    return pixmap


def test_large_grid_item_matches_macos_album_geometry_and_typography(qtbot):
    Metrics.apply_grid_item_scale("large")
    item = GridItem()
    qtbot.addWidget(item)

    assert (item.width(), item.height()) == (180, 228)
    assert (item.image_label.width(), item.image_label.height()) == (
        Metrics.GRID_ART_SIZE,
        Metrics.GRID_ART_SIZE,
    )
    item_layout = item.layout()
    assert item_layout is not None
    margins = item_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        Metrics.GRID_CARD_MARGIN,
        Metrics.GRID_CARD_MARGIN,
        Metrics.GRID_CARD_MARGIN,
        Metrics.GRID_CARD_MARGIN,
    )
    assert item.title_label.font().pointSize() == Metrics.FONT_GRID_TITLE
    assert item.subtitle_label.font().pointSize() == Metrics.FONT_GRID_SUBTITLE


def test_grid_caption_geometry_tracks_accessibility_font_scale() -> None:
    try:
        Metrics.apply_font_scale("125%")
        Metrics.apply_grid_item_scale("large")

        assert Metrics.FONT_GRID_TITLE == 16
        assert Metrics.FONT_GRID_SUBTITLE == 15
        assert Metrics.GRID_TEXT_HEIGHT == 28
        assert Metrics.GRID_SUBTITLE_HEIGHT == 25
        assert Metrics.GRID_ITEM_H == 239
    finally:
        Metrics.apply_font_scale("100%")
        Metrics.apply_grid_item_scale("large")


def test_grid_size_preset_controls_shared_music_and_photo_card_geometry(qtbot):
    try:
        Metrics.apply_grid_item_scale("small")
        small_item = GridItem()
        qtbot.addWidget(small_item)

        assert small_item.width() == Metrics.GRID_ITEM_W == 151
        assert small_item.height() == Metrics.GRID_ITEM_H == 198
        assert small_item.image_label.width() == Metrics.GRID_ART_SIZE == 143

        grid = _mount_grid(qtbot)
        grid.setRecords([GridItemModel(key="photo", title="Photo")])
        qtbot.waitUntil(lambda: len(grid.gridItems) == 1, timeout=2000)
        assert grid.gridItems[0].size() == small_item.size()
    finally:
        Metrics.apply_grid_item_scale("large")


def test_shared_grid_item_supports_music_and_photo_models(qtbot):
    item = GridItem(checkable=True)
    qtbot.addWidget(item)

    item.setModel(
        GridItemModel(
            key="album",
            title="Album",
            subtitle="Artist",
            placeholder_glyph="album",
        )
    )
    assert item.title_label.text() == "Album"
    assert item.subtitle_label.text() == "Artist"
    assert item.subtitle_label.isVisibleTo(item)

    item.setModel(
        GridItemModel(
            key="photo",
            title="Photo.jpg",
            image=_solid_pixmap((20, 40, 60)),
            checked=True,
            placeholder_glyph="photo",
        )
    )
    assert item.title_label.text() == "Photo.jpg"
    assert item.subtitle_label.text() == ""
    assert not item.subtitle_label.isVisibleTo(item)
    assert item.checkbox is not None
    assert item.checkbox.isChecked()
    assert item.image_label.pixmap() is not None


def test_shared_grid_item_treats_null_pixmap_as_photo_placeholder(qtbot):
    item = GridItem()
    qtbot.addWidget(item)

    item.setModel(
        GridItemModel(
            key="photo",
            title="Loading.jpg",
            image=QPixmap(),
            placeholder_glyph="photo",
        )
    )

    assert "background: rgba(" in item.image_label.styleSheet()


def test_shared_pooled_grid_owns_keyed_selection_checking_and_context(qtbot):
    grid = _mount_grid(qtbot, checkable=True)
    records = [
        GridItemModel(key="one", title="One", checked=False),
        GridItemModel(key="two", title="Two", checked=True),
    ]
    contexts: list[tuple[object, int, QPoint]] = []
    grid.contextRequested.connect(
        lambda key, index, pos: contexts.append((key, index, pos))
    )

    grid.setRecords(records, fallback_index=0)
    qtbot.waitUntil(lambda: len(grid.gridItems) == 2, timeout=2000)

    first = grid.gridItems[0]
    assert isinstance(first, GridItem)
    qtbot.mouseClick(first, Qt.MouseButton.LeftButton)
    assert grid.currentIndex() == 0

    grid.setRecordChecked("one", True)
    first_record = grid.recordAt(0)
    assert first_record is not None
    assert first_record.checked is True
    assert first.checkbox is not None and first.checkbox.isChecked()

    pos = first.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pos,
        first.mapToGlobal(pos),
    )
    QApplication.sendEvent(first, event)
    assert contexts and contexts[-1][:2] == ("one", 0)


def test_shared_pooled_grid_updates_visible_artwork_by_record_key(qtbot):
    grid = _mount_grid(qtbot)
    grid.setRecords([GridItemModel(key="photo", title="Photo")])
    qtbot.waitUntil(lambda: len(grid.gridItems) == 1, timeout=2000)

    pixmap = _solid_pixmap((90, 120, 150))
    grid.setRecordArtwork("photo", pixmap, dominant_color=(90, 120, 150))

    record = grid.recordAt(0)
    item = grid.gridItems[0]
    assert record is not None and record.image is pixmap
    assert isinstance(item, GridItem)
    assert item.image_label.pixmap() is not None


def test_shared_pooled_grid_rebinds_visible_same_key_records(qtbot):
    grid = _mount_grid(qtbot, checkable=True)
    grid.setRecords([GridItemModel(key="same", title="Before", checked=False)])
    qtbot.waitUntil(lambda: len(grid.gridItems) == 1, timeout=2000)

    grid.setRecords(
        [GridItemModel(key="same", title="After", checked=True)],
        reset_scroll=False,
    )
    qtbot.waitUntil(
        lambda: isinstance(grid.gridItems[0], GridItem)
        and grid.gridItems[0].title_label.text() == "After",
        timeout=2000,
    )

    item = grid.gridItems[0]
    assert isinstance(item, GridItem)
    assert item.checkbox is not None and item.checkbox.isChecked()
