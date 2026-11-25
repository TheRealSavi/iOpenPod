# SPDX-License-Identifier: GPL-3.0-only
"""Build a read-only Extras / Mods list from the included firmware composition.

Native list cloning and event encoding adapted from osos-lab's UI compiler,
commit d2c8e357d58591bdaa70bb6be9da191f489554a6 (GPL-3.0-only).
Input offsets refer to the hash-qualified prepared 2.0.5 OS in build_classic.py.
"""

import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from .classic_resources import (
    RESOURCE_SCRATCH_BYTES,
    blocks,
    pack_blocks,
    put,
    stock_resource_locations,
    stock_resources,
    u32,
)
from .classic_target import DRAM_BASE, DRAM_FILE

EXTRAS_SCREEN = 0x0DAD01CC
EXTRAS_ITEMS = 2
MOD_SCREEN = 0x0CF00010
MOD_LAYOUT = 0x0CF00011
MOD_ITEMS = 0x0CF00012
MOD_ENTRY = 0x0CF00013
MOD_SCREEN_NAME = "iOpenPod_Mods_Screen"
MOD_LAYOUT_NAME = "iOpenPod_Mods_Layout"
MOD_PREVIEW_NAME = "iOpenPod_Mods_Preview"
MOD_PREVIEW_IMAGE = Path(__file__).with_name("classic_about") / "mods_gear.png"


@dataclass(frozen=True)
class IncludedMod:
    id: str
    name: str
    version: str = "0.1.0-dev"


def included_mods(
    *,
    homebrew_eapps: bool,
    dark_mode: bool = False,
    now_playing_artwork: bool = False,
    bootloader_report: bool = False,
    long_audio: bool = False,
    photo_zoom: bool = False,
    title_bar_clock: bool = False,
    mono_audio: bool = False,
) -> tuple[IncludedMod, ...]:
    result = [
        IncludedMod("org.iopenpod.version-string", "Mod Version String"),
        IncludedMod("org.iopenpod.about-version", "Mod Version in About"),
    ]
    if homebrew_eapps:
        result.append(IncludedMod("org.iopenpod.homebrew", "Unsigned Game Manifests"))
    result.append(IncludedMod("org.iopenpod.mod-menu", "Mod Menu", "0.1.2-dev"))
    result.append(IncludedMod("org.iopenpod.mod-memory", "Expanded Mod Memory"))
    if dark_mode:
        result.append(
            IncludedMod(
                "org.iopenpod.dark-mode", "Light / Dark Appearance", "0.1.5-dev"
            )
        )
    if now_playing_artwork:
        result.append(
            IncludedMod(
                "org.iopenpod.now-playing-preview-artwork",
                "Now Playing Preview Artwork",
                "0.1.3-dev",
            )
        )
    if bootloader_report:
        result.append(
            IncludedMod("org.iopenpod.bootloader-report", "Bootloader Report")
        )
    if long_audio:
        result.extend(
            (
                IncludedMod("org.iopenpod.long-audio-playback", "Long Audio Playback"),
                IncludedMod("org.iopenpod.fast-audio-seek", "Fast Audio Seeking"),
            )
        )
    if photo_zoom:
        result.append(
            IncludedMod("org.iopenpod.photo-zoom", "Photo Zoom and Pan", "0.3.0-dev")
        )
    if title_bar_clock:
        result.append(
            IncludedMod("org.iopenpod.title-bar-clock", "Title Bar Clock", "0.1.1-dev")
        )
    if mono_audio:
        result.append(IncludedMod("org.iopenpod.mono-audio", "Mono Audio", "0.1.1-dev"))
    return tuple(result)


def mod_records(
    *,
    homebrew_eapps: bool,
    dark_mode: bool = False,
    now_playing_artwork: bool = False,
    bootloader_report: bool = False,
    long_audio: bool = False,
    photo_zoom: bool = False,
    title_bar_clock: bool = False,
    mono_audio: bool = False,
) -> list[dict[str, str]]:
    return [
        asdict(mod)
        for mod in included_mods(
            homebrew_eapps=homebrew_eapps,
            dark_mode=dark_mode,
            now_playing_artwork=now_playing_artwork,
            bootloader_report=bootloader_report,
            long_audio=long_audio,
            photo_zoom=photo_zoom,
            title_bar_clock=title_bar_clock,
            mono_audio=mono_audio,
        )
    ]


def serialized_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def event(
    name: str, action: str, arguments: tuple[str, ...] = (), *, native_flag: bool = True
) -> bytes:
    return (
        serialized_string(name)
        + (b"1" if native_flag else b"0")
        + serialized_string("")
        + struct.pack("<I", 1)
        + serialized_string(action)
        + struct.pack("<I", len(arguments))
        + b"".join(serialized_string(argument) for argument in arguments)
    )


@dataclass
class MenuResources:
    stock: dict[tuple[str, int], bytes]
    added: dict[tuple[str, int], bytes] = field(
        default_factory=dict[tuple[str, int], bytes]
    )
    next_id: int = 0x0CF00020
    replacements: set[tuple[str, int]] = field(default_factory=set[tuple[str, int]])
    names: dict[str, int] = field(default_factory=dict[str, int])

    def allocate(self) -> int:
        result = self.next_id
        self.next_id += 1
        return result

    def source(self, text: str) -> int:
        string, source = self.allocate(), self.allocate()
        self.added["Str ", string] = text.encode("utf-8") + b"\0"
        self.added["SORC", source] = pack_blocks(
            [(0x534F5243, struct.pack("<III", 0x80, string, 1))]
        )
        return source

    def clone_list_layout(self, title: int) -> None:
        # The stock Notes alternate list fills the screen and supplies marquee
        # scrolling for labels longer than the display. Reuse its View templates.
        layout: list[tuple[int, bytes]] = []
        titles = tables = 0
        for kind, body in blocks(self.stock["SLyt", 0x0DAD09FB]):
            changed = bytearray(body)
            instance_list = self.allocate()
            instances: list[tuple[int, bytes]] = []
            for instance_kind, instance in blocks(self.stock["SSin", u32(body, 0)]):
                new_instance = bytearray(instance)
                instance_id = self.allocate()
                put(new_instance, 0, instance_id)
                instances.append((instance_kind, bytes(new_instance)))
                for binding_kind in ("VCrv", "VCvs"):
                    key = binding_kind, u32(instance, 0)
                    if key not in self.stock:
                        continue
                    binding = self.stock[key]
                    if binding_kind == "VCvs":
                        bindings: list[tuple[int, bytes]] = []
                        for target, value in blocks(binding):
                            rebound = bytearray(value)
                            if u32(instance, 4) == 0x0DAD01A1:
                                if target != 0x0DAD01A6 or len(value) != 16:
                                    raise ValueError("Unexpected native title binding")
                                put(rebound, 12, title)
                                titles += 1
                            if target == 0x3F1:
                                if len(value) != 8:
                                    raise ValueError("Unexpected native list binding")
                                put(rebound, 4, MOD_ITEMS)
                                tables += 1
                            bindings.append((target, bytes(rebound)))
                        binding = pack_blocks(bindings)
                    self.added[binding_kind, instance_id] = binding
            self.added["SSin", instance_list] = pack_blocks(instances)
            put(changed, 0, instance_list)
            layout.append((kind, bytes(changed)))
        if (titles, tables) != (1, 1):
            raise ValueError("Native Mods list must have one title and one item table")
        self.added["SLyt", MOD_LAYOUT] = pack_blocks(layout)

    def add_preview_layout(
        self, screen: int, layout: int, preview: int, template: int, replacement: int
    ) -> None:
        """Register a native screen variant with its own template or view layout."""
        layouts: list[tuple[int, bytes]] = []
        for kind, original_body in blocks(self.stock["SLyt", layout]):
            body = bytearray(original_body)
            instances: list[tuple[int, bytes]] = []
            for instance_kind, original in blocks(self.stock["SSin", u32(body, 0)]):
                instance = bytearray(original)
                old_id, new_id = u32(instance, 0), self.allocate()
                put(instance, 0, new_id)
                for offset in (4, 8):
                    if u32(instance, offset) == template:
                        put(instance, offset, replacement)
                for binding in ("VCrv", "VCvs"):
                    if (binding, old_id) in self.stock:
                        self.added[binding, new_id] = self.stock[binding, old_id]
                instances.append((instance_kind, bytes(instance)))
            instance_list = self.allocate()
            self.added["SSin", instance_list] = pack_blocks(instances)
            put(body, 0, instance_list)
            layouts.append((kind, bytes(body)))
        self.added["SLyt", preview] = pack_blocks(layouts)
        self.added["SEVT", preview] = self.stock["SEVT", layout]
        key = "SLst", screen
        variants = blocks(self.added.get(key, self.stock[key]))
        kind, variant = next(
            (k, bytearray(v)) for k, v in variants if u32(v, 0) == layout
        )
        put(variant, 0, preview)
        self.added[key] = pack_blocks([*variants, (kind, bytes(variant))])


def _mods_gear_bitmap() -> bytes:
    with Image.open(MOD_PREVIEW_IMAGE) as image:
        if image.mode != "P" or image.size != (142, 87):
            raise ValueError(
                "Expected an indexed gear in the native Games preview frame"
            )
        image.apply_transparency()
        palette = image.getpalette("BGRA")
        if palette is None:
            raise ValueError("Missing Mods preview palette")
        pixels = struct.pack("<I", len(palette) // 4) + bytes(palette) + image.tobytes()
        width, height = image.size
    return (
        struct.pack("<4H5I", 0x64, 0, width, 8, 0, 0, height, width, len(pixels))
        + pixels
    )


def add_mods_preview(menu: MenuResources) -> None:
    games_layout, games_template, games_view_layout = 0x0DAD01DC, 0x0DAD019C, 0x0DAD01A0
    preview, mods_view_layout = menu.allocate(), menu.allocate()
    bitmap, source = menu.allocate(), menu.allocate()
    menu.added["BMap", bitmap] = _mods_gear_bitmap()
    menu.added["IMAG", bitmap] = struct.pack("<I", bitmap)
    menu.added["SORC", source] = pack_blocks(
        [(0x534F5243, struct.pack("<3I", 0x80, bitmap, 1))]
    )
    # ROM iteration indexes children of stock templates, including appended children.
    # Give each immutable bitmap its own child so a cached dice image is never reused.
    children = blocks(menu.stock["View", games_template])
    kind, image_view = next((k, bytearray(v)) for k, v in children if k == 0x696D6167)
    gear_child = menu.allocate()
    put(image_view, 0x30, gear_child)
    put(image_view, 0x74, source)
    children.append((kind, bytes(image_view)))
    menu.added["View", games_template] = pack_blocks(children)
    for layout, show_gear in ((games_view_layout, False), (mods_view_layout, True)):
        visibility: list[tuple[int, bytes]] = []
        for _, child in children:
            child_id = u32(child, 0x30)
            visible = show_gear if child_id == gear_child else not show_gear
            visibility.append((child_id, pack_blocks([(1005, bytes([visible]))])))
        menu.added["VLyt", layout] = pack_blocks(visibility)
    menu.added["TEVT", mods_view_layout] = menu.stock["TEVT", games_view_layout]
    menu.add_preview_layout(
        EXTRAS_SCREEN, games_layout, preview, games_view_layout, mods_view_layout
    )
    menu.names[MOD_PREVIEW_NAME] = preview


def menu_resources(raw: bytes, mods: tuple[IncludedMod, ...]) -> MenuResources:
    resources = MenuResources(stock_resources(raw))
    original_ids = {key[1] for key in resources.stock}
    if any(0x0CF00000 <= value < 0x0CF00100 for value in original_ids):
        raise ValueError("Native resource ID overlaps the reserved mod range")
    stock, added = resources.stock, resources.added
    prototype = next(
        body for _, body in blocks(stock["ITEM", 65]) if u32(body, 0x30) == 0x0DAD0C7B
    )
    if len(prototype) != 152 or not mods:
        raise ValueError("Invalid native row prototype or empty mod composition")
    title = resources.source("Mods")

    def row(item_id: int, source: int, *, readonly: bool) -> bytes:
        result = bytearray(prototype)
        put(result, 0x30, item_id)
        put(result, 0x68, source)
        if readonly:
            put(result, 0x60, 2)  # Native text row, no submenu arrow.
        return bytes(result)

    added["ITEM", MOD_ITEMS] = pack_blocks(
        [
            (0, row(resources.allocate(), resources.source(mod.name), readonly=True))
            for mod in mods
        ]
    )
    resources.clone_list_layout(title)
    added["SCST", MOD_SCREEN] = stock["SCST", 0x0DAD0C6A]
    added["CEVT", MOD_SCREEN] = struct.pack("<I", 0)
    layouts = blocks(stock["SLst", 0x0DAD09FA])
    if len(layouts) != 1:
        raise ValueError("Unexpected native Notes layout list")
    kind, layout = layouts[0]
    changed_layout = bytearray(layout)
    put(changed_layout, 0, MOD_LAYOUT)
    added["SLst", MOD_SCREEN] = pack_blocks([(kind, bytes(changed_layout))])
    added["SEVT", MOD_LAYOUT] = (
        struct.pack("<I", 2)
        + event("button.menu.up", "navigator.PopTopScreen")
        + event("button.menu.pressandhold", "navigator.PopToMainScreen")
    )
    add_mods_preview(resources)
    added["ITEM", EXTRAS_ITEMS] = pack_blocks(
        [
            *blocks(stock["ITEM", EXTRAS_ITEMS]),
            (0, row(MOD_ENTRY, title, readonly=False)),
        ]
    )
    events = stock["CEVT", EXTRAS_SCREEN]
    added["CEVT", EXTRAS_SCREEN] = (
        struct.pack("<I", u32(events, 0) + 2)
        + events[4:]
        + event(
            f"list.pid.{MOD_ENTRY}.chosen",
            "navigator.PushScreen",
            (MOD_SCREEN_NAME, MOD_LAYOUT_NAME, "foregroundpush"),
        )
        + event(
            f"list.pid.{MOD_ENTRY}.delayedselected",
            "navigator.SwitchLayout",
            (MOD_PREVIEW_NAME,),
            native_flag=False,  # All nine stock Extras highlight events use ASCII zero.
        )
    )
    return resources


def emit_menu_header(resources: MenuResources, raw: bytes) -> str:
    """Emit immutable data consumed by the small ARM resource-install hook."""
    locations = stock_resource_locations(raw)
    lines = [
        f"#define IOP_RESOURCE_SCRATCH_BYTES {RESOURCE_SCRATCH_BYTES}",
        "struct iop_resource { uint32_t type, id; const void *data; uint32_t size; };",
        "struct iop_extension { uint32_t type, id; const unsigned char *stock, *tail; uint32_t stock_size, tail_size, count; };",
        "struct iop_resource_name { const char *name; uint32_t id; };",
        "static const struct iop_resource_name iop_menu_names[] = {",
        f'    {{"{MOD_SCREEN_NAME}", 0x{MOD_SCREEN:08x}u}},',
        f'    {{"{MOD_LAYOUT_NAME}", 0x{MOD_LAYOUT:08x}u}},',
        *(
            f'    {{"{name}", 0x{value:08x}u}},'
            for name, value in resources.names.items()
        ),
        "};",
    ]
    entries: list[str] = []
    extensions: list[str] = []
    for index, ((kind, resource_id), data) in enumerate(resources.added.items()):
        original = (
            None
            if (kind, resource_id) in resources.replacements
            else resources.stock.get((kind, resource_id))
        )
        kind_word = int.from_bytes(kind.encode("ascii"), "big")
        name = f"iop_menu_resource_{index}"
        if original is None:
            entries.append(
                f"    {{0x{kind_word:08x}u, 0x{resource_id:08x}u, {name}, sizeof({name})}},"
            )
        else:
            if data[4 : len(original)] != original[4:] or len(data) <= len(original):
                raise ValueError(
                    "A menu extension must preserve the complete stock prefix"
                )
            location = locations.get((kind, resource_id))
            if location is None:
                raise ValueError("Menu extension has no native directory entry")
            offset, size = location
            if offset < DRAM_FILE or raw[offset : offset + size] != original:
                raise ValueError(
                    "Menu extension differs from its native directory entry"
                )
            if len(data) > RESOURCE_SCRATCH_BYTES:
                raise ValueError(
                    "Menu extension exceeds reserved initialization workspace"
                )
            count = u32(data, 0)
            data = data[len(original) :]
            address = DRAM_BASE + offset - DRAM_FILE
            extensions.append(
                f"    {{0x{kind_word:08x}u, 0x{resource_id:08x}u, (const unsigned char *)0x{address:08x}u, {name}, {len(original)}, sizeof({name}), {count}}},"
            )
        lines.append(
            f"static const unsigned char {name}[] __attribute__((aligned(4))) = {{"
        )
        lines.extend(
            "    " + ",".join(f"0x{x:02x}" for x in data[p : p + 16]) + ","
            for p in range(0, len(data), 16)
        )
        lines.append("};")
    lines.extend(
        ["static const struct iop_resource iop_menu_resources[] = {", *entries, "};"]
    )
    lines.extend(
        [
            "static const struct iop_extension iop_menu_extensions[] = {",
            *extensions,
            "};",
        ]
    )
    return "\n".join(lines) + "\n"
