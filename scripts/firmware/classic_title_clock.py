"""Compose the full-width Classic title bars from their native child views."""

import struct
from dataclasses import dataclass

from .classic_menu import MenuResources
from .classic_resources import blocks, pack_blocks, put, u32

TEXT = 0x74657874
SOURCE = 0x534F5243
TIME_SOURCE = 0x292  # Localized clock-model string, also used by Date & Time.
CLOCK_FIRST = 0x0CF00200
LAYOUT_FIRST = 0x0CF00300
HALF, PARTIAL = 0x0DAD01A8, 0x0DAD01A9
LEFT, RIGHT, VISIBLE = 1001, 1003, 1005
CLOCK_RIGHT = 315


@dataclass(frozen=True)
class TitleBar:
    template: int
    title: int
    layouts: tuple[int, ...]
    # Indicators in native construction order for bars with a centered title.
    indicator_chain: tuple[int, ...] = ()


BARS = (
    TitleBar(0x0DAD01A1, 0x0DAD01A6, (0x0DAD01A7, HALF, PARTIAL)),
    TitleBar(
        0x0DAD020C,
        0x0DAD020E,
        (0x0DAD020D, 0x0DAD08D6, 0x0DAD08D7, 0x0DAD08D8, 0x0DAD08D9),
        (0x0DAD08D2, 0x0DAD08D3, 0x0DAD08D4, 0x0DAD08D5),
    ),
    TitleBar(0x0DAD05EE, 0x0DAD01A6, (0x0DAD05EF,)),
    TitleBar(
        0x0DAD0757,
        0x0DAD075D,
        (0x0DAD0761, 0x0DAD0762),
        (0x0DAD0759, 0x0DAD075A, 0x0DAD075B, 0x0DAD075C),
    ),
)


def anchor(offset: int, relative: int = 0, edge: int = 0) -> bytes:
    return struct.pack("<iII", offset, relative, edge)


def layout_with(original: bytes, changes: dict[int, dict[int, bytes]]) -> bytes:
    children = dict(blocks(original))
    for child, properties in changes.items():
        options = dict(blocks(children.get(child, bytes(4))))
        options.update(properties)
        children[child] = pack_blocks(list(options.items()))
    return pack_blocks(list(children.items()))


def title_clock_resources(menu: MenuResources) -> str:
    """Install the four child views and emit the qualified layout selector."""
    if any(
        CLOCK_FIRST <= resource_id < LAYOUT_FIRST + 16
        for resources in (menu.stock, menu.added)
        for _, resource_id in resources
    ):
        raise ValueError("Title Bar Clock resource ID collision")
    if menu.stock["SORC", TIME_SOURCE] != pack_blocks(
        [(SOURCE, struct.pack("<3I", 0x8080, 0x80AE, 1))]
    ):
        raise ValueError("Unexpected native local-time source")
    empty_source = menu.source("")
    cases: list[str] = []
    centered_clocks: list[str] = []
    for index, bar in enumerate(BARS):
        key = "View", bar.template
        views = blocks(menu.stock[key])
        by_id = {u32(body, 0x30): body for _, body in views}
        title = by_id[bar.title]
        if key in menu.added or len(title) != 140 or u32(title, 0x4C) != TEXT:
            raise ValueError("Unexpected or already overridden title-bar template")
        clock_id = CLOCK_FIRST + index
        clock = bytearray(title)
        # View stores left/top/bottom/right. Layout options use top/left/bottom/right.
        # Let TextView measure the localized time instead of reserving blank
        # leading space in a fixed-width box beside the status indicators.
        clock[:12] = anchor(0, 0, 7)
        clock[36:48] = anchor(-5)
        put(clock, 0x30, clock_id)
        put(clock, 0x5C, 1)  # Plain TextView, with no alternator or marquee.
        put(clock, 0x64, empty_source)
        put(clock, 0x68, 0x0DAD0001)  # StatusBar_Font
        put(clock, 0x78, 2)  # Native trailing alignment
        put(clock, 0x84, 0)
        put(clock, 0x88, 0)
        # Paint after the backdrop. Subsequent siblings may anchor to the clock.
        views.insert(1, (TEXT, bytes(clock)))
        menu.added[key] = pack_blocks(views)
        menu.replacements.add(key)

        if bar.indicator_chain:
            if u32(title, 0x78) != 3:
                raise ValueError("Expected a centered title")
            centered_clocks.append(f"id == 0x{clock_id:08x}u")
        for layout in bar.layouts:
            layout_key = "VLyt", layout
            if layout_key in menu.added:
                raise ValueError("Title-bar layout already has a resource override")
            original = menu.stock.get(layout_key, bytes(4))
            original_options = {
                child: dict(blocks(body)) for child, body in blocks(original)
            }
            # Reference the clock's fixed trailing edge so the native title proxy
            # recognizes this layout and the title stays at x6 as time width varies.
            geometry = {bar.title: {LEFT: anchor(6 - CLOCK_RIGHT, clock_id, 4)}}
            if bar.indicator_chain:
                previous = clock_id
                for child in bar.indicator_chain:
                    gap = 5 if previous == clock_id else 3
                    geometry[child] = {
                        LEFT: anchor(0, 0, 7),
                        RIGHT: anchor(-gap, previous, 2),
                    }
                    if original_options.get(child, {}).get(VISIBLE, b"\1") != b"\0":
                        previous = child
                # The radio indicator is constructed after the title. Reserve
                # its slot without depending on a later sibling's first layout.
                geometry[bar.title][RIGHT] = (
                    anchor(-96, clock_id, 2)
                    if previous == 0x0DAD08D5
                    else anchor(-6, previous, 2)
                )
            else:
                geometry[0x0DAD01A3] = {RIGHT: anchor(-5, clock_id, 2)}
            # Restore stock geometry explicitly when the native view is reused.
            reset = {
                child: {
                    prop: original_options.get(child, {}).get(
                        prop,
                        by_id[child][0:12] if prop == LEFT else by_id[child][36:48],
                    )
                    for prop in options
                }
                for child, options in geometry.items()
            }
            reset[clock_id] = {SOURCE: struct.pack("<I", empty_source), VISIBLE: b"\0"}
            menu.added[layout_key] = layout_with(original, reset)
            menu.replacements.add(layout_key)
            if layout in (HALF, PARTIAL):
                continue
            enabled = dict(geometry)
            enabled[clock_id] = {SOURCE: struct.pack("<I", TIME_SOURCE), VISIBLE: b"\1"}
            alternate = LAYOUT_FIRST + len(cases)
            menu.added["VLyt", alternate] = layout_with(original, enabled)
            cases.append(f"    case 0x{layout:08x}u: return 0x{alternate:08x}u;")
    return "\n".join(
        [
            f"#define CLOCK_FIRST 0x{CLOCK_FIRST:08x}u",
            f"#define CLOCK_COUNT {len(BARS)}u",
            "static int originally_centered(unsigned id) {",
            f"    return {' || '.join(centered_clocks)};",
            "}",
            "static unsigned clock_layout(unsigned id) {",
            "    switch (id) {",
            *cases,
            "    default: return id;",
            "    }",
            "}",
            "",
        ]
    )
