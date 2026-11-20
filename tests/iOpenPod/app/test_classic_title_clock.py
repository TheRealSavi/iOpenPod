"""Verify the composed Classic title bars against Apple's bundled resource bank."""

import struct
from collections import Counter

import pytest
from scripts.firmware.classic_menu import MenuResources, included_mods, menu_resources
from scripts.firmware.classic_resources import blocks, u32
from scripts.firmware.classic_title_clock import (
    BARS,
    CLOCK_FIRST,
    HALF,
    LAYOUT_FIRST,
    LEFT,
    PARTIAL,
    RIGHT,
    SOURCE,
    TEXT,
    TIME_SOURCE,
    VISIBLE,
    title_clock_resources,
)

from iOpenPod.app.firmware.classic_shared import OSOS_LENGTH_OFFSET, OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware


@pytest.fixture(scope="module")
def menu() -> MenuResources:
    image = bundled_firmware()
    osos = image[OSOS_OFFSET : OSOS_OFFSET + u32(image, OSOS_LENGTH_OFFSET)]
    resources = menu_resources(
        osos, included_mods(homebrew_eapps=True, title_bar_clock=True)
    )
    title_clock_resources(resources)
    return resources


def test_named_bars_resolve_from_their_real_screens(menu: MenuResources) -> None:
    expected = {
        0x0DAD062B: (0x0DAD01A1, HALF),  # Date & Time
        0x0DAD0A57: (0x0DAD020C, 0x0DAD08D9),  # photo album thumbnails
        0x0DAD0D47: (0x0DAD020C, 0x0DAD020D),  # Stopwatch stopped
        0x0DAD0D48: (0x0DAD020C, 0x0DAD020D),  # Stopwatch running
        0x0DAD0D4F: (0x0DAD01A1, HALF),  # Stopwatch menu
        0x0DAD0D51: (0x0DAD01A1, 0x0DAD01A7),  # Stopwatch summary
        0x0DAD083C: (0x0DAD01A1, 0x0DAD01A7),  # Genius introduction
        0x0DAD07E7: (0x0DAD0757, 0x0DAD0761),  # multiple Genius Mixes
        0x0DAD07E8: (0x0DAD0757, 0x0DAD0762),  # single Genius Mix
        0x0DAD0979: (0x0DAD020C, 0x0DAD08D7),  # video playback overlay
    }
    templates = {bar.template for bar in BARS}
    # Full-size photos and the video frame without playback controls have no bar.
    for screen, bar in {**expected, 0x0DAD0A58: None, 0x0DAD0978: None}.items():
        bars = [
            (u32(instance, 4), u32(instance, 8))
            for _, section in blocks(menu.stock["SLyt", screen])
            for _, instance in blocks(menu.stock["SSin", u32(section, 0)])
            if u32(instance, 4) in templates
        ]
        assert bars == ([] if bar is None else [bar])


def test_title_bar_inventory_covers_the_stock_screen_layouts(
    menu: MenuResources,
) -> None:
    templates = {bar.template for bar in BARS}
    uses: Counter[tuple[int, int]] = Counter()
    titled_screens = 0
    for (kind, _), layout in menu.stock.items():
        if kind != "SLyt":
            continue
        screen_bars = {
            (u32(view, 4), u32(view, 8))
            for _, section in blocks(layout)
            for _, view in blocks(menu.stock.get(("SSin", u32(section, 0)), bytes(4)))
            if u32(view, 4) in templates
        }
        uses.update(screen_bars)
        titled_screens += bool(screen_bars)
    assert titled_screens == 322
    assert set(uses) == {
        (bar.template, layout)
        for bar in BARS
        for layout in bar.layouts
        if layout != PARTIAL
    }
    assert [[uses[bar.template, layout] for layout in bar.layouts] for bar in BARS] == [
        [74, 126, 0],
        [70, 3, 5, 4, 1],
        [39],
        [1, 1],
    ]


def test_full_bars_keep_their_screen_bindings_and_use_the_native_clock(
    menu: MenuResources,
) -> None:
    alternate = LAYOUT_FIRST
    for index, bar in enumerate(BARS):
        original_views = blocks(menu.stock["View", bar.template])
        views = blocks(menu.added["View", bar.template])
        kind, clock = views.pop(1)
        assert views == original_views
        assert kind == TEXT and u32(clock, 0x30) == CLOCK_FIRST + index
        assert u32(clock, 0x78) == 2 and u32(clock, 0x5C) == 1
        assert u32(clock, 0) == 244 and struct.unpack_from("<i", clock, 36)[0] == -5
        title = next(body for _, body in views if u32(body, 0x30) == bar.title)
        assert u32(clock, 0x70) == u32(title, 0x70)
        for layout in bar.layouts:
            stock = dict(blocks(menu.stock.get(("VLyt", layout), bytes(4))))
            off = dict(blocks(menu.added["VLyt", layout]))
            clock_id = CLOCK_FIRST + index
            assert dict(blocks(off[clock_id]))[VISIBLE] == bytes(1)
            assert dict(blocks(off[bar.title]))[LEFT] == title[:12]
            if bar.indicator_chain:
                assert dict(blocks(off[bar.title]))[RIGHT] == title[36:48]
            if layout in (HALF, PARTIAL):
                continue
            on = dict(blocks(menu.added["VLyt", alternate]))
            alternate += 1
            assert dict(blocks(on[clock_id])) == {
                SOURCE: struct.pack("<I", TIME_SOURCE),
                VISIBLE: b"\x01",
            }
            opts = dict(blocks(on[bar.title]))
            assert struct.unpack("<iII", opts[LEFT]) == (6 - 244, clock_id, 2)
            if bar.indicator_chain:
                assert u32(title, 0x78) == 3
                assert u32(opts[RIGHT], 4) in (*bar.indicator_chain, clock_id)
            for child, native in stock.items():
                for prop, value in blocks(native):
                    if prop not in (LEFT, RIGHT):
                        assert dict(blocks(on[child]))[prop] == value
                        assert dict(blocks(off[child]))[prop] == value
    assert alternate == LAYOUT_FIRST + 9
    assert ("VLyt", alternate) not in menu.added


def test_clock_is_opt_in_and_listed_in_the_release() -> None:
    assert (
        included_mods(homebrew_eapps=False, title_bar_clock=True)[-1].name
        == "Title Bar Clock"
    )
    assert all(
        mod.name != "Title Bar Clock" for mod in included_mods(homebrew_eapps=False)
    )
    image = bundled_firmware()
    assert (
        b"Title Bar Clock\0"
        in image[OSOS_OFFSET : OSOS_OFFSET + u32(image, OSOS_LENGTH_OFFSET)]
    )
