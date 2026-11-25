# SPDX-License-Identifier: GPL-3.0-only
"""Semantic Classic appearance compilation, native Settings row and ARM hooks.

Native Settings encoding/hooks derive from osos-lab d2c8e357 (GPL-3.0-only).
The palette, explicit artwork roles and embedded reversible patch format are
iOpenPod's. No runtime dependency on osos-lab or external theme packs.
"""

import struct
from dataclasses import dataclass
from functools import partial

from .classic_bitmaps import RGB, Bitmap, pack565, unpack565
from .classic_deltas import encode_xor_delta
from .classic_menu import MenuResources
from .classic_resources import stock_resource_locations
from .classic_settings import add_settings_toggle

BASE: RGB = (18, 24, 31)
RAISED: RGB = (31, 41, 52)
PRIMARY: RGB = (237, 243, 249)
SECONDARY: RGB = (183, 198, 213)
MUTED: RGB = (120, 139, 158)
ACCENT: RGB = (119, 194, 255)
SELECT_LOW: RGB = (35, 104, 163)
SELECT_HIGH: RGB = (44, 112, 173)
VALUE = 0x0CF00100
ROW = 0x0CF00101
LIGHT = 0x0CF00102
DARK = 0x0CF00103
TITLE = 0x0CF00104
TITLE_SOURCE = 0x0CF00105
SAVE_ERROR = 0x0CF00106
PREVIEW_IMAGE = 0x0CF00107
MOON = 0x0CF00108
AUTO = 0x0CF00109
AUTO_LIGHT_START_HOUR = 7
AUTO_LIGHT_END_HOUR = 18


def contrast(a: RGB, b: RGB) -> float:
    """WCAG sRGB contrast, after the Classic's RGB565 channel quantization."""

    def luminance(color: RGB) -> float:
        channels = [v / 255 for v in unpack565(pack565(color))]
        linear = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in channels
        ]
        return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


def mix(low: RGB, high: RGB, value: int) -> RGB:
    return (
        low[0] + (high[0] - low[0]) * value // 255,
        low[1] + (high[1] - low[1]) * value // 255,
        low[2] + (high[2] - low[2]) * value // 255,
    )


def shade(color: RGB) -> int:
    return (color[0] * 54 + color[1] * 183 + color[2] * 19) // 256


def artwork_color(role: str, color: RGB) -> RGB:
    """Role-selected transforms retain highlights above shadows and all alpha."""
    value = shade(color)
    if role == "title":
        return mix((13, 19, 26), (49, 62, 76), value)
    if role == "surface":
        return mix((6, 10, 15), RAISED, value)
    if role == "genius-thumb":
        # This bitmap embeds the arrow in its opaque gray button. Separate the
        # dark arrow/antialias ramp from the bright beveled button surface.
        if value <= 128:
            return PRIMARY
        if value < 196:
            return mix(PRIMARY, SELECT_LOW, (value - 128) * 255 // 68)
        return mix(SELECT_LOW, SELECT_HIGH, (value - 196) * 255 // 59)
    if role == "cover-placeholder":
        if value <= 184:
            return mix(BASE, (56, 72, 88), value * 255 // 184)
        return mix((112, 140, 167), PRIMARY, (value - 184) * 255 // 71)
    if role == "preview":
        return mix((12, 18, 25), (48, 64, 80), value)
    if role == "selection":
        return mix(SELECT_LOW, SELECT_HIGH, value)
    if role == "track":
        return mix((20, 28, 37), (64, 82, 101), value)
    if role == "progress":
        return mix((106, 180, 237), ACCENT, value)
    if role == "scrollbar":
        return mix((132, 151, 171), SECONDARY, value)
    if role == "primary-glyph":
        return PRIMARY
    if role == "secondary-glyph":
        return SECONDARY
    if role == "muted-glyph":
        return MUTED
    if role == "ink":
        # Only neutral interface ink. Battery green/red and pictogram hues stay.
        if max(color) - min(color) > 18:
            return color
        return mix(PRIMARY, BASE, value)
    raise ValueError(f"Unknown artwork role {role}")


def bitmap_roles() -> dict[int, str]:
    """Explicit resource IDs; photographs and coverage masks are never selected."""
    roles: dict[int, str] = {}

    def add(role: str, values: tuple[int, ...] | range) -> None:
        for value in values:
            key = 0x0DAD0000 + value
            if key in roles:
                raise ValueError("Bitmap has conflicting semantic roles")
            roles[key] = role

    add("title", (0x12A, 0x12C, 0xAE0, 0xB01))
    add("preview", (0x12D, 0x5DA))
    add(
        "surface",
        (
            *range(0x178, 0x17B),
            *range(0x17E, 0x181),
            *range(0x197, 0x19A),
            0x369,
            0x36A,
            0x489,  # World Clock row backdrop; separate from face/hand artwork.
        ),
    )
    add(
        "selection",
        (
            *range(0x17B, 0x17E),
            0x36B,
            *range(0x184, 0x187),
            *range(0x190, 0x193),
            0x8C1,
            0x8C2,
        ),
    )
    add(
        "track",
        (
            *range(0x181, 0x184),
            *range(0x18D, 0x190),
            *range(0x874, 0x877),
            0x880,
            0x882,
            *range(0xE0F, 0xE12),
        ),
    )
    add("progress", (*range(0x877, 0x87A), 0x881, 0x883))
    add("scrollbar", (*range(0x122, 0x125), 0xAFF))
    add("native-status", (0x142, *range(0x143, 0x15C)))
    add("primary-glyph", (0x88C,))
    add("secondary-glyph", (0x87F,))
    add("muted-glyph", (0x887,))
    add("genius-thumb", (0x8C0,))
    add("placeholder", (*range(0x12F, 0x136), *range(0x71F, 0x72B)))
    add("cover-placeholder", (0x128, 0x129))
    add(
        "ink",
        (
            0x12B,
            0x868,
            0x869,
            0x86A,
            0x86E,
            0x86F,
            0x872,
            0x873,
            0x889,
            0x88A,
            0x88B,
            *range(0x88E, 0x8A4),
            0xC08,
            0x72C,
            0x72E,
        ),
    )
    return roles


def themed_bitmap(
    resource_id: int,
    role: str,
    raw: bytes,
    locations: dict[tuple[str, int], tuple[int, int]],
) -> bytes:
    offset, size = locations["BMap", resource_id]
    bitmap = Bitmap.parse(raw[offset : offset + size])
    if role == "placeholder":
        return placeholder_bitmap(bitmap)
    if role != "native-status":
        return bitmap.recolor(partial(artwork_color, role))
    # Apple already drew light lock/battery symbols for its black status bar.
    # Reuse that shading and low-battery red, rather than invert metal/glass.
    counterpart = 0x0DAD0141 if resource_id == 0x0DAD0142 else resource_id + 0x19
    start, length = locations["BMap", counterpart]
    source = Bitmap.parse(raw[start : start + length])
    if resource_id in (0x0DAD015A, 0x0DAD015B):
        # Native plug/bolt shading is too dim on raised charcoal. Retain their
        # original coverage and make these meaningful status glyphs light ink.
        source = Bitmap.parse(source.recolor(lambda _color: PRIMARY))
    if source.width > bitmap.width or source.height != bitmap.height:
        raise ValueError("Native status counterpart geometry changed")
    pixels = bytearray(bitmap.width * bitmap.height * 4)
    source_pixels = source.rgba()
    left = (bitmap.width - source.width) // 2
    for y in range(bitmap.height):
        row = (y * bitmap.width + left) * 4
        pixels[row : row + source.width * 4] = source_pixels[
            y * source.width * 4 : (y + 1) * source.width * 4
        ]
    return bitmap.replace_rgba(bytes(pixels))


def placeholder_bitmap(bitmap: Bitmap) -> bytes:
    """Keep native proxy symbols and shading, replacing their pale backdrops.

    These qualified 55-pixel proxies have the backdrop in their leftmost column.
    Estimate each symbol's coverage relative to that row, then average by source
    color so palette indices stay intact. All of this runs on the build host.
    """
    pixels = bitmap.rgba()

    def color_at(offset: int) -> RGB:
        return pixels[offset], pixels[offset + 1], pixels[offset + 2]

    totals: dict[RGB, list[int]] = {}
    for y in range(bitmap.height):
        background = color_at(y * bitmap.width * 4)
        surface = mix((12, 18, 25), (38, 51, 66), shade(background))
        for x in range(bitmap.width):
            color = color_at((y * bitmap.width + x) * 4)
            distance = max(abs(a - b) for a, b in zip(color, background, strict=True))
            ink = mix(
                (112, 140, 167),
                PRIMARY,
                max(0, min(255, (shade(color) - 120) * 255 // 135)),
            )
            mapped = mix(surface, ink, min(255, distance * 255 // 30))
            total = totals.setdefault(color, [0, 0, 0, 0])
            for channel in range(3):
                total[channel] += mapped[channel]
            total[3] += 1

    def transform(color: RGB) -> RGB:
        if total := totals.get(color):
            return total[0] // total[3], total[1] // total[3], total[2] // total[3]
        return artwork_color("surface", color)  # Unused palette entries.

    return bitmap.recolor(transform)


@dataclass(frozen=True)
class AppearancePatch:
    resource_id: int
    role: str
    address: int
    original: bytes
    changed: bytes


def artwork_patches(raw: bytes) -> tuple[AppearancePatch, ...]:
    locations = stock_resource_locations(raw)
    patches: list[AppearancePatch] = []
    for resource_id, role in sorted(bitmap_roles().items()):
        offset, size = locations["BMap", resource_id]
        original = raw[offset : offset + size]
        changed = themed_bitmap(resource_id, role, raw, locations)
        # Indexed assets only need palette updates, often tens of bytes for an
        # entire screen. Trim unchanged ends, preserving all original addresses.
        differences = [
            i
            for i, pair in enumerate(zip(original, changed, strict=True))
            if pair[0] != pair[1]
        ]
        if differences:
            first, end = differences[0], differences[-1] + 1
            patches.append(
                AppearancePatch(
                    resource_id,
                    role,
                    0x08000000 + offset - 0xB798 + first,
                    original[first:end],
                    changed[first:end],
                )
            )
    return tuple(patches)


def settings_resources(menu: MenuResources) -> None:
    """Insert Appearance after Brightness; preserve every original row/event."""
    if any(0x0CF00100 <= key[1] <= 0x0CF00120 for key in menu.stock | menu.added):
        raise ValueError("Appearance IDs overlap existing resources")
    menu.added["Str ", LIGHT] = b"Light\0"
    menu.added["Str ", DARK] = b"Dark\0"
    menu.added["Str ", AUTO] = b"Auto\0"
    menu.added["Str ", TITLE] = b"Appearance\0"
    menu.added["Str ", SAVE_ERROR] = b"Not saved\0"
    add_settings_toggle(
        menu,
        title="Appearance",
        title_id=TITLE,
        source_id=TITLE_SOURCE,
        row_id=ROW,
        value_id=VALUE,
        after=0x0DAD0C72,
        action_name="iOpenPod_Appearance_Toggle",
        preview_name="iOpenPod_Appearance_Preview",
        image_binding=(0x8900, PREVIEW_IMAGE),
    )
    # An anti-aliased coverage mask, rendered in Apple's native icon color.
    size = 80
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            covered = sum(
                (x + dx - 38) ** 2 + (y + dy - 40) ** 2 <= 31**2
                and (x + dx - 51) ** 2 + (y + dy - 29) ** 2 > 28**2
                for dy in (0.125, 0.375, 0.625, 0.875)
                for dx in (0.125, 0.375, 0.625, 0.875)
            )
            pixels.append(covered * 255 // 16)
    menu.added["BMap", MOON] = (
        struct.pack("<4H5I", 8, 0, size, 8, 0, 0, size, size, len(pixels)) + pixels
    )


def emit_appearance_header(raw: bytes) -> str:
    patches = artwork_patches(raw)
    lines = [
        "/* Generated from the hash-qualified stock OS. */",
        "struct appearance_patch { unsigned char *address; const unsigned char *xor_bytes; uint32_t size; };",
        f"#define APPEARANCE_VALUE 0x{VALUE:08x}u",
        f"#define APPEARANCE_LIGHT 0x{LIGHT:08x}u",
        f"#define APPEARANCE_DARK 0x{DARK:08x}u",
        f"#define APPEARANCE_AUTO 0x{AUTO:08x}u",
        f"#define APPEARANCE_LIGHT_START_HOUR {AUTO_LIGHT_START_HOUR}u",
        f"#define APPEARANCE_LIGHT_END_HOUR {AUTO_LIGHT_END_HOUR}u",
        f"#define APPEARANCE_SAVE_ERROR 0x{SAVE_ERROR:08x}u",
        f"#define APPEARANCE_PREVIEW_IMAGE 0x{PREVIEW_IMAGE:08x}u",
        f"#define APPEARANCE_MOON 0x{MOON:08x}u",
    ]
    entries: list[str] = []
    for name, steps in (("first", 65), ("second", 52)):
        colors = [
            mix(SELECT_LOW, SELECT_HIGH, level * 255 // steps)
            for level in range(steps + 1)
        ]
        lines.append(f"static const uint32_t appearance_gradient_{name}[] = {{")
        lines.append(",".join(f"0x{r:02x}{g:02x}{b:02x}u" for r, g, b in colors))
        lines.append("};")
    for index, patch in enumerate(patches):
        delta = encode_xor_delta(patch.original, patch.changed)
        lines.append(f"static const unsigned char appearance_delta_{index}[] = {{")
        lines.extend(
            "    " + ",".join(f"0x{value:02x}" for value in delta[p : p + 24]) + ","
            for p in range(0, len(delta), 24)
        )
        lines.append("};")
        entries.append(
            f"    {{(unsigned char *)0x{patch.address:08x}u, appearance_delta_{index}, {len(patch.original)}}},"
        )
    lines.extend(
        [
            "static const struct appearance_patch appearance_patches[] = {",
            *entries,
            "};",
        ]
    )
    return "\n".join(lines) + "\n"
