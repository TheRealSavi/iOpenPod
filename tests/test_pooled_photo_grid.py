from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from iopenpod.gui.styles import Colors, display_accent_rgb
from iopenpod.gui.widgets.photoTile import PhotoGridTile
from iopenpod.gui.widgets.pooledPhotoGrid import PhotoTileModel, PooledPhotoGridView


def _mount_grid(
    qtbot,
    *,
    width: int = 920,
    height: int = 620,
    checkable: bool = False,
    settings_service=None,
) -> tuple[QScrollArea, PooledPhotoGridView]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = PooledPhotoGridView(
        checkable=checkable,
        settings_service=settings_service,
    )
    scroll.setWidget(grid)
    grid.attachScrollArea(scroll)

    qtbot.addWidget(scroll)
    scroll.resize(width, height)
    scroll.show()
    qtbot.wait(50)
    return scroll, grid


def _build_records(count: int) -> list[PhotoTileModel]:
    return [
        PhotoTileModel(
            key=f"photo-{index:04d}",
            title=f"Photo {index:04d}",
            checked=bool(index % 2),
        )
        for index in range(count)
    ]


def _as_photo_tile(widget: QWidget) -> PhotoGridTile:
    assert isinstance(widget, PhotoGridTile)
    return widget


def _record_key_at(grid: PooledPhotoGridView, index: int) -> object:
    record = grid.recordAt(index)
    assert record is not None
    return record.key


def _record_is_unchecked(grid: PooledPhotoGridView, index: int) -> bool:
    record = grid.recordAt(index)
    return record is not None and not record.checked


def _tile_is_unchecked(widget: QWidget) -> bool:
    checkbox = _as_photo_tile(widget).checkbox
    return checkbox is not None and not checkbox.isChecked()


def _send_context_menu(widget: PhotoGridTile) -> None:
    pos = widget.rect().center() if widget.rect().isValid() else QPoint(8, 8)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pos,
        widget.mapToGlobal(pos),
    )
    QApplication.sendEvent(widget, event)


def _solid_pixmap(rgb: tuple[int, int, int]) -> QPixmap:
    pixmap = QPixmap(48, 48)
    pixmap.fill(QColor(*rgb))
    return pixmap


def test_pooled_photo_grid_recycles_widgets_on_scroll(qtbot):
    scroll, grid = _mount_grid(qtbot)
    records = _build_records(3000)

    grid.setRecords(records, fallback_index=0)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    initial_widget_ids = {id(widget) for widget in grid.findChildren(PhotoGridTile)}
    initial_tiles = [cast(PhotoGridTile, widget) for widget in grid.gridItems]
    initial_titles = [tile.title_label.text() for tile in initial_tiles]

    assert len(initial_widget_ids) < 100

    bar = scroll.verticalScrollBar()
    assert bar is not None
    bar.setValue(max(1, bar.maximum() // 2))
    qtbot.waitUntil(
        lambda: grid.gridItems
        and cast(PhotoGridTile, grid.gridItems[0]).title_label.text() not in initial_titles,
        timeout=2000,
    )

    scrolled_widget_ids = {id(widget) for widget in grid.findChildren(PhotoGridTile)}
    assert len(scrolled_widget_ids) < 100
    assert len(initial_widget_ids & scrolled_widget_ids) >= len(initial_widget_ids) // 2


def test_pooled_photo_grid_preserves_checked_state_by_record_key(qtbot):
    _scroll, grid = _mount_grid(qtbot, checkable=True)
    records = _build_records(50)

    grid.setRecords(records, fallback_index=0)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    grid.setRecordChecked("photo-0000", True)
    first = grid.recordAt(0)

    assert first is not None
    assert first.checked is True
    tile = _as_photo_tile(grid.gridItems[0])
    checkbox = tile.checkbox
    assert checkbox is not None
    assert checkbox.isChecked() is True


def test_pooled_photo_grid_groups_selected_records_under_section_headers(qtbot):
    _scroll, grid = _mount_grid(qtbot, checkable=True)
    records = [
        PhotoTileModel(key="unselected-1", title="Unselected 1", checked=False),
        PhotoTileModel(key="selected-1", title="Selected 1", checked=True),
        PhotoTileModel(key="unselected-2", title="Unselected 2", checked=False),
        PhotoTileModel(key="selected-2", title="Selected 2", checked=True),
    ]

    grid.setRecords(records, fallback_index=0)
    grid.setGroupBySelected(True)
    qtbot.waitUntil(lambda: len(grid.gridItems) == 4, timeout=2000)

    assert [_record_key_at(grid, index) for index in range(grid.count())] == [
        "selected-1",
        "selected-2",
        "unselected-1",
        "unselected-2",
    ]
    selected_header = grid.findChild(QLabel, "selectedPhotoSectionHeader")
    unselected_header = grid.findChild(QLabel, "unselectedPhotoSectionHeader")
    assert selected_header is not None and not selected_header.isHidden()
    assert unselected_header is not None and not unselected_header.isHidden()
    assert selected_header.styleSheet().endswith("border: none;")
    assert selected_header.y() < grid._visible_widgets[0].y()
    assert unselected_header.y() < grid._visible_widgets[2].y()

    grid.setRecordChecked("selected-1", False)

    assert [_record_key_at(grid, index) for index in range(grid.count())] == [
        "selected-2",
        "unselected-1",
        "selected-1",
        "unselected-2",
    ]


def test_pooled_photo_grid_rebinds_same_order_selection_refreshes(qtbot):
    _scroll, grid = _mount_grid(qtbot, checkable=True)
    grid.setRecords(
        [
            PhotoTileModel(key="alpha", title="Alpha", checked=True),
            PhotoTileModel(key="bravo", title="Bravo", checked=True),
        ],
        fallback_index=0,
    )
    grid.setGroupBySelected(True)
    qtbot.waitUntil(lambda: len(grid.gridItems) == 2, timeout=2000)

    grid.setRecords(
        [
            PhotoTileModel(key="alpha", title="Alpha", checked=False),
            PhotoTileModel(key="bravo", title="Bravo", checked=False),
        ],
        reset_scroll=False,
        fallback_index=0,
    )

    selected_header = grid.findChild(QLabel, "selectedPhotoSectionHeader")
    unselected_header = grid.findChild(QLabel, "unselectedPhotoSectionHeader")
    assert selected_header is not None
    assert unselected_header is not None
    qtbot.waitUntil(
        lambda: all(
            _record_is_unchecked(grid, index)
            for index in range(grid.count())
        )
        and selected_header.isHidden()
        and not unselected_header.isHidden(),
        timeout=2000,
    )
    assert all(
        _tile_is_unchecked(tile)
        for tile in grid.gridItems
    )


def test_pooled_photo_grid_emits_context_menu_target(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    records = _build_records(10)
    captured: list[tuple[object, int, QPoint]] = []

    grid.contextRequested.connect(
        lambda key, index, pos: captured.append((key, index, pos))
    )
    grid.setRecords(records, fallback_index=0)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    _send_context_menu(_as_photo_tile(grid.gridItems[0]))

    assert captured
    assert captured[0][0] == "photo-0000"
    assert captured[0][1] == 0
    assert isinstance(captured[0][2], QPoint)
    assert grid.currentIndex() == 0


def test_photo_tile_uses_dominant_color_for_card_background(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    rgb = (200, 40, 20)
    grid.setRecords([
        PhotoTileModel(
            key="photo-0001",
            title="Color",
            pixmap=_solid_pixmap(rgb),
            dominant_color=rgb,
        )
    ], fallback_index=-1)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    tile = _as_photo_tile(grid.gridItems[0])
    display_rgb = display_accent_rgb(
        rgb,
        background=Colors.BG_DARK,
        target_ratio=Colors.GRID_ART_CONTRAST_TARGET,
    )

    assert f"rgba({display_rgb[0]}, {display_rgb[1]}, {display_rgb[2]}, 30)" in tile.styleSheet()


def test_photo_tile_respects_rounded_artwork_setting(qtbot):
    settings_service = SimpleNamespace(
        get_effective_settings=lambda: SimpleNamespace(rounded_artwork=True)
    )
    _scroll, grid = _mount_grid(qtbot, settings_service=settings_service)
    grid.setRecords([
        PhotoTileModel(
            key="photo-0001",
            title="Rounded",
            pixmap=_solid_pixmap((20, 120, 220)),
        )
    ], fallback_index=0)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    tile = _as_photo_tile(grid.gridItems[0])
    rendered = tile.image_label.pixmap()

    assert rendered is not None
    assert rendered.toImage().pixelColor(0, 0).alpha() == 0
