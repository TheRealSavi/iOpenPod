# SPDX-License-Identifier: GPL-3.0-only
"""Compose native Classic Settings rows and their preview layouts."""

import struct

from .classic_menu import MenuResources, event, serialized_string
from .classic_resources import blocks, pack_blocks, put, u32


def add_settings_toggle(
    menu: MenuResources,
    *,
    title: str,
    title_id: int,
    source_id: int,
    row_id: int,
    value_id: int,
    after: int,
    action_name: str,
    preview_name: str,
    image_binding: tuple[int, int],
) -> None:
    """Extend the current composition, retaining other settings and their events."""
    menu.added["SORC", source_id] = pack_blocks(
        [
            (0x534F5243, struct.pack("<III", 0x80, title_id, 1)),
            (0x534F5243, struct.pack("<III", 0x8900, value_id, 10)),
        ]
    )
    original = blocks(menu.added.get(("ITEM", 65), menu.stock["ITEM", 65]))
    prototype = next(body for _, body in original if u32(body, 0x30) == 0x0DAD0C76)
    if len(prototype) != 152:
        raise ValueError("Settings toggle prototype changed")
    row = bytearray(prototype)
    put(row, 0x30, row_id)
    put(row, 0x68, source_id)
    updated: list[tuple[int, bytes]] = []
    for kind, body in original:
        updated.append((kind, body))
        if u32(body, 0x30) == after:
            updated.append((0, bytes(row)))
    if len(updated) != len(original) + 1:
        raise ValueError("Settings row anchor changed")
    menu.added["ITEM", 65] = pack_blocks(updated)
    menu.replacements.add(("ITEM", 65))
    screen = 0x0DAD0C6A
    events = menu.added.get(("CEVT", screen), menu.stock["CEVT", screen])
    action = (
        serialized_string(f"list.pid.{row_id}.chosen")
        + b"1"
        + serialized_string(action_name)
        + struct.pack("<I", 0)
    )
    menu.names[preview_name] = settings_preview(menu, title, image_binding, value_id)
    menu.added["CEVT", screen] = (
        struct.pack("<I", u32(events, 0) + 2)
        + events[4:]
        + action
        + event(
            f"list.pid.{row_id}.delayedselected",
            "navigator.SwitchLayout",
            (preview_name,),
        )
    )
    menu.replacements.add(("CEVT", screen))


def settings_preview(
    menu: MenuResources, title: str, image_binding: tuple[int, int], value_id: int
) -> int:
    """Clone Apple's Brightness preview with the setting's own bindings."""
    template, layout, screen = 0x0DAD0C39, 0x0DAD0C84, 0x0DAD0C6A
    preview, preview_view = menu.allocate(), menu.allocate()
    title_source = menu.source(title)
    original = bytearray(menu.stock["VLyt", template])
    put(original, 0x24, title_source)
    sources: dict[int, int] = {}
    for view_id, (service, property_id) in (
        (0x0DAD0C30, image_binding),
        (0x0DAD0C31, (0x8900, value_id)),
    ):
        source = menu.allocate()
        sources[view_id] = source
        menu.added["SORC", source] = pack_blocks(
            [(0x534F5243, struct.pack("<III", service, property_id, 1))]
        )
    views: list[tuple[int, bytes]] = []
    for view_id, options in blocks(bytes(original)):
        if view_id in sources:
            options = pack_blocks(
                [
                    (
                        kind,
                        struct.pack("<I", sources[view_id])
                        if kind == 0x534F5243
                        else body,
                    )
                    for kind, body in blocks(options)
                ]
            )
        views.append((view_id, options))
    menu.added["VLyt", preview_view] = pack_blocks(views)
    menu.added["TEVT", preview_view] = menu.stock["TEVT", template]
    menu.add_preview_layout(screen, layout, preview, template, preview_view)
    menu.replacements.add(("SLst", screen))
    return preview
