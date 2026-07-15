from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

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
