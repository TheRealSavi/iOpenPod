from __future__ import annotations

from typing import cast

from PyQt6.QtWidgets import QScrollArea, QWidget

from GUI.widgets.photoTile import PhotoGridTile
from GUI.widgets.pooledPhotoGrid import PhotoTileModel, PooledPhotoGridView


def _mount_grid(
    qtbot,
    *,
    width: int = 920,
    height: int = 620,
    checkable: bool = False,
) -> tuple[QScrollArea, PooledPhotoGridView]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = PooledPhotoGridView(checkable=checkable)
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
