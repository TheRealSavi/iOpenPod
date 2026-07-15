from __future__ import annotations

from typing import Any, cast

from PIL import Image
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtWidgets import QApplication, QScrollArea, QScrollBar

import iopenpod.gui.imgMaker as img_maker
from iopenpod.gui.styles import Colors
from iopenpod.gui.widgets.MBGridView import ArtworkResult, MusicBrowserGrid
from iopenpod.gui.widgets.MBGridViewItem import GridItemRenderState, MusicBrowserGridItem


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


def _mount_grid(
    qtbot,
    *,
    width: int = 920,
    height: int = 620,
    multi_select: bool = False,
) -> tuple[QScrollArea, MusicBrowserGrid]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = MusicBrowserGrid(multi_select_enabled=multi_select)
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


def _selected_titles(grid: MusicBrowserGrid) -> list[str]:
    return [str(item.get("title")) for item in grid.selectedItemData()]


def _send_context_menu(widget: MusicBrowserGridItem) -> None:
    pos = widget.rect().center() if widget.rect().isValid() else QPoint(8, 8)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pos,
        widget.mapToGlobal(pos),
    )
    QApplication.sendEvent(widget, event)


def _compact_css(widget: MusicBrowserGridItem) -> str:
    return "".join(widget.styleSheet().split())


def test_grid_item_keeps_existing_artwork_tint_in_dark_theme(qtbot, monkeypatch):
    monkeypatch.setattr(Colors, "_active_mode", "dark")
    item = MusicBrowserGridItem()
    qtbot.addWidget(item)

    item._apply_color_theme(
        GridItemRenderState(display_dominant_color=(86, 112, 144))
    )

    css = _compact_css(item)
    assert "background-color:rgba(86,112,144,30);" in css
    assert "border:none;" in css
    assert "background-color:rgba(86,112,144,55);" in css


def test_grid_item_uses_stronger_artwork_tint_in_light_theme(qtbot, monkeypatch):
    monkeypatch.setattr(Colors, "_active_mode", "light")
    item = MusicBrowserGridItem()
    qtbot.addWidget(item)

    item._apply_color_theme(
        GridItemRenderState(display_dominant_color=(86, 112, 144))
    )

    css = _compact_css(item)
    assert "background-color:rgba(86,112,144,48);" in css
    assert "border:none;" in css
    assert "background-color:rgba(86,112,144,82);" in css


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


def test_grid_modifier_clicks_select_without_opening(qtbot):
    _scroll, grid = _mount_grid(qtbot, multi_select=True)
    grid.populateGrid(_build_items(20))
    qtbot.waitUntil(lambda: len(grid.gridItems) >= 4, timeout=2000)

    opened: list[str] = []
    grid.item_selected.connect(lambda item: opened.append(str(item.get("title"))))
    items = _grid_items(grid)

    qtbot.mouseClick(
        items[0],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert opened == []
    assert _selected_titles(grid) == ["Album 0000"]
    assert items[0].isSelected()

    qtbot.mouseClick(
        items[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )
    assert opened == []
    assert _selected_titles(grid) == ["Album 0000", "Album 0001", "Album 0002"]
    assert [item.isSelected() for item in _grid_items(grid)[:3]] == [True, True, True]

    qtbot.mouseClick(
        items[1],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert opened == []
    assert _selected_titles(grid) == ["Album 0000", "Album 0002"]

    qtbot.mouseClick(items[3], Qt.MouseButton.LeftButton)
    assert opened == ["Album 0003"]
    assert _selected_titles(grid) == ["Album 0000", "Album 0002"]


def test_grid_click_emits_rendered_artwork_colors(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    grid.populateGrid(_build_items(1, with_art=True))
    qtbot.waitUntil(lambda: len(grid.gridItems) == 1, timeout=2000)
    grid._art_cache[1000] = ArtworkResult(
        Image.new("RGBA", (16, 16), (86, 112, 144, 255)),
        (86, 112, 144),
        {"text": (255, 255, 255), "text_secondary": (225, 230, 238)},
    )
    grid._apply_art_to_visible_widgets(1000)
    qtbot.waitUntil(
        lambda: _grid_items(grid)[0].item_data.get("dominant_color") == (86, 112, 144),
        timeout=2000,
    )

    emitted: list[dict] = []
    grid.item_selected.connect(emitted.append)
    qtbot.mouseClick(_grid_items(grid)[0], Qt.MouseButton.LeftButton)

    assert len(emitted) == 1
    assert emitted[0]["dominant_color"] == (86, 112, 144)
    assert emitted[0]["display_dominant_color"] == (86, 112, 144)


def test_grid_modifier_click_opens_when_multi_select_is_disabled(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    grid.populateGrid(_build_items(4))
    qtbot.waitUntil(lambda: len(grid.gridItems) >= 1, timeout=2000)

    opened: list[str] = []
    grid.item_selected.connect(lambda item: opened.append(str(item.get("title"))))

    qtbot.mouseClick(
        _grid_items(grid)[0],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )

    assert opened == ["Album 0000"]
    assert _selected_titles(grid) == []


def test_grid_context_menu_targets_selected_items_or_clicked_item(qtbot):
    _scroll, grid = _mount_grid(qtbot, multi_select=True)
    grid.populateGrid(_build_items(20))
    qtbot.waitUntil(lambda: len(grid.gridItems) >= 4, timeout=2000)
    first, second, third, fourth = _grid_items(grid)[:4]

    captured: list[list[str]] = []
    grid.item_context_requested.connect(
        lambda items, _pos: captured.append(
            [str(item.get("title")) for item in items]
        )
    )

    qtbot.mouseClick(
        first,
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.mouseClick(
        third,
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )

    _send_context_menu(second)
    assert captured[-1] == ["Album 0000", "Album 0001", "Album 0002"]

    _send_context_menu(fourth)
    assert captured[-1] == ["Album 0003"]
    assert _selected_titles(grid) == ["Album 0003"]


def test_grid_selection_survives_widget_recycling_without_leaking(qtbot):
    scroll, grid = _mount_grid(qtbot, height=260, multi_select=True)
    grid.populateGrid(_build_items(220))
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    first = _grid_items(grid)[0]
    qtbot.mouseClick(
        first,
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_titles(grid) == ["Album 0000"]
    assert first.isSelected()

    bar = _scroll_bar(scroll)
    bar.setValue(bar.maximum())
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") != "Album 0000",
        timeout=2000,
    )
    assert not any(item.isSelected() for item in _grid_items(grid))

    bar.setValue(0)
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("title") == "Album 0000",
        timeout=2000,
    )
    assert _grid_items(grid)[0].isSelected()


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


def test_grid_search_matches_symbol_variants(qtbot):
    _scroll, grid = _mount_grid(qtbot)
    item = {
        "title": "I’m",
        "artist": "Artist",
        "category": "Albums",
    }
    grid.populateGrid([item])

    grid.setSearchFilter("i'm")

    assert [record.source for record in grid._visible_records] == [item]


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


def test_source_reload_invalidates_grid_artwork_for_same_album_identity(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(img_maker, "get_artwork", lambda *args, **kwargs: None)

    _scroll, grid = _mount_grid(qtbot)
    items = _build_items(50, with_art=True)

    grid.populateGrid(items)
    qtbot.waitUntil(lambda: len(grid.gridItems) > 0, timeout=2000)

    art_key = items[0]["artwork_id_ref"]
    assert art_key is not None

    grid._on_art_loaded({art_key: _art_result((1, 2, 3))}, grid._load_id)
    qtbot.waitUntil(
        lambda: _grid_items(grid)[0].item_data.get("dominant_color") == (1, 2, 3),
        timeout=2000,
    )

    grid.populateGrid(items)
    qtbot.waitUntil(
        lambda: _grid_items(grid)
        and _grid_items(grid)[0].item_data.get("dominant_color") != (1, 2, 3),
        timeout=2000,
    )

    grid._on_art_loaded({art_key: _art_result((4, 5, 6))}, grid._load_id)
    qtbot.waitUntil(
        lambda: _grid_items(grid)[0].item_data.get("dominant_color") == (4, 5, 6),
        timeout=2000,
    )
