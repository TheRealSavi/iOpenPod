from __future__ import annotations

from typing import Any, cast

from PIL import Image
from PyQt6.QtWidgets import QScrollArea, QScrollBar

import GUI.imgMaker as img_maker
from GUI.widgets.MBGridView import MusicBrowserGrid
from GUI.widgets.MBGridViewItem import MusicBrowserGridItem


def _build_items(
    count: int,
    *,
    with_art: bool = False,
    start: int = 0,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index in range(start, start + count):
        items.append(
            {
                "title": f"Album {index:04d}",
                "subtitle": f"Artist {index % 17:02d}",
                "artist": f"Artist {index % 17:02d}",
                "album": f"Album {index:04d}",
                "category": "Albums",
                "filter_key": "album",
                "filter_value": f"Album {index:04d}",
                "artwork_id_ref": 1000 + index if with_art else None,
                "year": 2000 + (index % 20),
            }
        )
    return items


def _mount_grid(qtbot, *, width: int = 920, height: int = 620) -> tuple[QScrollArea, MusicBrowserGrid]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = MusicBrowserGrid()
    scroll.setWidget(grid)
    grid.attachScrollArea(scroll)

    qtbot.addWidget(scroll)
    scroll.resize(width, height)
    scroll.show()
    qtbot.wait(50)
    return scroll, grid


def _grid_items(grid: MusicBrowserGrid) -> list[MusicBrowserGridItem]:
    return [cast(MusicBrowserGridItem, widget) for widget in grid.gridItems]


def _scroll_bar(scroll: QScrollArea) -> QScrollBar:
    bar = scroll.verticalScrollBar()
    assert bar is not None
    return bar


def _art_result(rgb: tuple[int, int, int]) -> tuple[int, int, bytes, tuple[int, int, int], dict]:
    image = Image.new("RGBA", (16, 16), (*rgb, 255))
    return (
        image.width,
        image.height,
        image.tobytes("raw", "RGBA"),
        rgb,
        {"bg": rgb},
    )


def test_grid_uses_bounded_widget_pool_and_recycles_on_scroll(qtbot):
    scroll, grid = _mount_grid(qtbot)
    items = _build_items(3000)

    grid.populateGrid(items)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    initial_widgets = grid.findChildren(MusicBrowserGridItem)
    initial_widget_ids = {id(widget) for widget in initial_widgets}
    initial_titles = [widget.item_data.get("title") for widget in _grid_items(grid)]

    assert len(initial_widgets) < 100
    assert len(initial_widgets) == len(grid.gridItems) + len(grid._widget_pool)

    bar = _scroll_bar(scroll)
    bar.setValue(max(1, bar.maximum() // 2))
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") not in initial_titles,
        timeout=2000,
    )

    scrolled_widgets = grid.findChildren(MusicBrowserGridItem)
    scrolled_widget_ids = {id(widget) for widget in scrolled_widgets}

    assert len(scrolled_widgets) < 100
    assert len(initial_widget_ids & scrolled_widget_ids) >= len(initial_widget_ids) // 2
    assert len(scrolled_widgets) == len(grid.gridItems) + len(grid._widget_pool)


def test_grid_rebinds_cleanly_for_search_and_sort(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    items = _build_items(400)

    grid.populateGrid(items)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    grid.setSearchFilter("Album 0315")
    qtbot.waitUntil(
        lambda: len(grid._visible_records) == 1
        and len(grid.gridItems) == 1
        and _grid_items(grid)[0].item_data.get("title") == "Album 0315",
        timeout=2000,
    )

    grid.resetFilters()
    grid.setSort("title", reverse=True)
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") == "Album 0399",
        timeout=2000,
    )

    assert _grid_items(grid)[0].item_data.get("subtitle") == "Artist 08"


def test_stale_art_results_are_ignored_after_dataset_switch(qtbot, monkeypatch):
    monkeypatch.setattr(img_maker, "get_artwork", lambda *args, **kwargs: None)

    _scroll, grid = _mount_grid(qtbot)
    old_items = _build_items(50, with_art=True, start=0)
    new_items = _build_items(50, with_art=True, start=200)

    grid.populateGrid(old_items)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    stale_load_id = grid._load_id
    stale_art_key = old_items[0]["artwork_id_ref"]

    grid.populateGrid(new_items)
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") == "Album 0200",
        timeout=2000,
    )

    grid._on_art_loaded({stale_art_key: _art_result((1, 2, 3))}, stale_load_id)
    qtbot.wait(20)

    assert _grid_items(grid)[0].item_data.get("title") == "Album 0200"
    assert _grid_items(grid)[0].item_data.get("dominant_color") != (1, 2, 3)

    current_art_key = new_items[0]["artwork_id_ref"]
    grid._on_art_loaded({current_art_key: _art_result((4, 5, 6))}, grid._load_id)
    qtbot.waitUntil(
        lambda: _grid_items(grid)[0].item_data.get("dominant_color") == (4, 5, 6),
        timeout=2000,
    )


def test_search_requeues_artwork_after_pending_request_is_invalidated(qtbot, monkeypatch):
    monkeypatch.setattr(img_maker, "get_artwork", lambda *args, **kwargs: None)

    _scroll, grid = _mount_grid(qtbot)
    items = _build_items(400, with_art=True)

    grid.populateGrid(items)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    target = items[315]
    art_key = target["artwork_id_ref"]
    assert art_key is not None

    # Simulate an in-flight art batch from the pre-search viewport.
    grid._art_pending.add(art_key)

    grid.setSearchFilter("Album 0315")
    qtbot.waitUntil(
        lambda: len(grid._visible_records) == 1
        and _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") == "Album 0315",
        timeout=2000,
    )

    needed_keys = [record.artwork_key for record in grid._visible_records_needing_art()]

    assert art_key not in grid._art_pending
    assert needed_keys == [art_key]
