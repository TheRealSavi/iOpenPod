"""Appearance composition against the actual bundled native resource bank."""

import struct

import pytest
from scripts.firmware.classic_appearance import (
    ACCENT,
    AUTO,
    BASE,
    DARK,
    LIGHT,
    MOON,
    PREVIEW_IMAGE,
    PRIMARY,
    RAISED,
    ROW,
    SECONDARY,
    SELECT_HIGH,
    SELECT_LOW,
    TITLE_SOURCE,
    VALUE,
    artwork_color,
    artwork_patches,
    bitmap_roles,
    contrast,
    mix,
    settings_resources,
    themed_bitmap,
)
from scripts.firmware.classic_bitmaps import Bitmap
from scripts.firmware.classic_deltas import encode_xor_delta
from scripts.firmware.classic_menu import (
    emit_menu_header,
    included_mods,
    menu_resources,
)
from scripts.firmware.classic_resources import blocks, stock_resource_locations, u32

from iOpenPod.app.firmware.classic_shared import OSOS_LENGTH_OFFSET, OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware


@pytest.fixture(scope="module")
def osos() -> bytes:
    image = bundled_firmware()
    return image[OSOS_OFFSET : OSOS_OFFSET + u32(image, OSOS_LENGTH_OFFSET)]


def test_palette_readability_after_hardware_quantization() -> None:
    assert contrast(PRIMARY, BASE) >= 7
    assert contrast(SECONDARY, RAISED) >= 7
    assert contrast(ACCENT, RAISED) >= 4.5
    for shade in range(256):
        selected = mix(SELECT_LOW, SELECT_HIGH, shade)
        assert contrast(PRIMARY, selected) >= 4.5
        assert contrast(selected, BASE) >= 3
        title = artwork_color("title", (shade, shade, shade))
        assert contrast(PRIMARY, title) >= 7
        progress = artwork_color("progress", (shade, shade, shade))
        assert contrast(progress, artwork_color("track", (255, 255, 255))) >= 3


def test_world_clock_row_backdrop_is_dark_with_readable_text(osos: bytes) -> None:
    # Clock row SIEM 0x0dad04da binds SORC 0x17c. Its static image source
    # supplies WorldClock_Graybar_Image as destination 13 (row background).
    locations = stock_resource_locations(osos)
    offset, size = locations["SORC", 0x17C]
    bindings = blocks(osos[offset : offset + size])
    assert (0x534F5243, struct.pack("<3I", 0x80, 0x0DAD0489, 13)) in bindings
    offset, size = locations["BMap", 0x0DAD0489]
    data = osos[offset : offset + size]
    if role := bitmap_roles().get(0x0DAD0489):
        data = themed_bitmap(0x0DAD0489, role, osos, locations)
    bitmap = Bitmap.parse(data)
    assert (bitmap.width, bitmap.height) == (5, 80)
    pixels = bitmap.rgba()
    for y in range(bitmap.height):
        i = (y * bitmap.width + bitmap.width // 2) * 4
        if pixels[i + 3] == 0:
            continue
        color = (pixels[i], pixels[i + 1], pixels[i + 2])
        assert max(color) <= 64, f"White clock row at y={y}: {color}"
        assert contrast(PRIMARY, color) >= 7
        assert contrast(SECONDARY, color) >= 7
    # Preserve day/night semantics and their matched face, cap and hand artwork.
    assert all(rid not in bitmap_roles() for rid in range(0x0DAD048A, 0x0DAD04CE))


def test_stock_resources_remain_byte_exact_after_dark_light_cycle(osos: bytes) -> None:
    changed = bytearray(osos)
    patches = artwork_patches(osos)
    assert 100 <= len(patches) <= 150
    for _ in range(2):
        for patch in patches:
            offset = patch.address - 0x08000000 + 0xB798
            delta = bytes(
                a ^ b for a, b in zip(patch.original, patch.changed, strict=True)
            )
            changed[offset : offset + len(delta)] = bytes(
                a ^ b
                for a, b in zip(
                    changed[offset : offset + len(delta)], delta, strict=True
                )
            )
        if _ == 0:
            assert changed != osos
    assert changed == osos
    # RGB565 placeholders need pixel deltas. Only compressed packets occupy
    # extra RAM; the native decoder applies them directly to the stock images.
    assert (
        sum(len(encode_xor_delta(p.original, p.changed)) for p in patches) < 80 * 1024
    )


def test_appearance_resources_stay_within_the_small_memory_budget(osos: bytes) -> None:
    baseline = menu_resources(osos, included_mods(homebrew_eapps=True))
    themed = menu_resources(osos, included_mods(homebrew_eapps=True, dark_mode=True))
    settings_resources(themed)
    # Native resource registration makes owned copies. Count those separately
    # from the linked payload, including complete replacement resource bodies.
    extra = sum(map(len, themed.added.values())) - sum(
        map(len, baseline.added.values())
    )
    assert 0 < extra < 24 * 1024


def test_theme_preserves_native_bitmap_geometry_alpha_and_indices(osos: bytes) -> None:
    locations = stock_resource_locations(osos)
    for resource_id, role in bitmap_roles().items():
        offset, size = locations["BMap", resource_id]
        source = Bitmap.parse(osos[offset : offset + size])
        updated = Bitmap.parse(themed_bitmap(resource_id, role, osos, locations))
        assert source.data[: source.start] == updated.data[: updated.start]
        if role == "native-status":
            counterpart = (
                0x0DAD0141 if resource_id == 0x0DAD0142 else resource_id + 0x19
            )
            at, count = locations["BMap", counterpart]
            native = Bitmap.parse(osos[at : at + count])
            if resource_id in (0x0DAD015A, 0x0DAD015B):
                native = Bitmap.parse(native.recolor(lambda _color: PRIMARY))
            left = (source.width - native.width) // 2
            for y in range(source.height):
                assert (
                    updated.rgba()[
                        (y * source.width + left) * 4 : (
                            y * source.width + left + native.width
                        )
                        * 4
                    ]
                    == native.rgba()[y * native.width * 4 : (y + 1) * native.width * 4]
                )
        else:
            assert source.rgba()[3::4] == updated.rgba()[3::4]
        if source.colors and role != "native-status":
            assert source.data[source.pixels :] == updated.data[updated.pixels :]
    # Clock hands, map outlines and native coverage masks keep their meaning.
    assert not any(0x0DAD0490 <= rid <= 0x0DAD04CD for rid in bitmap_roles())
    assert not any(0x0DAD0A05 <= rid <= 0x0DAD0A55 for rid in bitmap_roles())


@pytest.mark.parametrize("color", [(37, 183, 68), (220, 50, 20), (34, 110, 194)])
def test_status_ink_preserves_battery_and_pictogram_hues(
    color: tuple[int, int, int],
) -> None:
    assert artwork_color("ink", color) == color


def test_settings_row_has_controller_action_and_dynamic_value(osos: bytes) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=True, dark_mode=True))
    settings_resources(menu)
    before, after = blocks(menu.stock["ITEM", 65]), blocks(menu.added["ITEM", 65])
    assert [(kind, body) for kind, body in after if u32(body, 0x30) != ROW] == before
    at = next(i for i, (_, body) in enumerate(after) if u32(body, 0x30) == ROW)
    assert u32(after[at - 1][1], 0x30) == 0x0DAD0C72
    assert len(after[at][1]) == 152
    assert u32(after[at][1], 0x68) == TITLE_SOURCE
    sources = blocks(menu.added["SORC", TITLE_SOURCE])
    assert struct.unpack("<III", sources[1][1]) == (0x8900, VALUE, 10)
    events = menu.added["CEVT", 0x0DAD0C6A]
    original = menu.stock["CEVT", 0x0DAD0C6A]
    assert events[4 : len(original)] == original[4:]
    assert u32(events, 0) == u32(original, 0) + 2
    assert b"iOpenPod_Appearance_Toggle" in events
    assert b"navigator.SwitchLayout" in events[len(original) :]
    assert menu.added["Str ", LIGHT] == b"Light\0"
    assert menu.added["Str ", DARK] == b"Dark\0"
    assert menu.added["Str ", AUTO] == b"Auto\0"
    assert Bitmap.parse(menu.added["BMap", MOON]).format == 8
    assert any(
        struct.pack("<III", 0x8900, PREVIEW_IMAGE, 1) in value
        for (kind, _), value in menu.added.items()
        if kind == "SORC"
    )
    assert menu.names["iOpenPod_Appearance_Preview"] in {
        u32(body, 0) for _, body in blocks(menu.added["SLst", 0x0DAD0C6A])
    }
    assert "iOpenPod_Appearance_Preview" in emit_menu_header(menu, osos)


def test_dark_mode_is_optional_in_composition() -> None:
    assert "org.iopenpod.dark-mode" not in {
        m.id for m in included_mods(homebrew_eapps=True)
    }
    assert "org.iopenpod.dark-mode" in {
        m.id for m in included_mods(homebrew_eapps=True, dark_mode=True)
    }


@pytest.mark.parametrize(
    "payload",
    [b"", bytes(27), bytes(28), struct.pack("<4H5I", 8, 0, 1, 8, 0, 0, 1, 2, 0)],
)
def test_bitmap_rejects_malformed_layout(payload: bytes) -> None:
    with pytest.raises(ValueError):
        Bitmap.parse(payload)


def test_grayscale_masks_cannot_be_recolored() -> None:
    bitmap = Bitmap.parse(struct.pack("<4H5I", 8, 0, 1, 8, 0, 0, 1, 1, 1) + b"\x80")
    with pytest.raises(ValueError, match="coverage masks"):
        bitmap.recolor(lambda color: color)


@pytest.mark.parametrize(
    "resource_id,minimum", [(0x0DAD087F, 4.5), (0x0DAD0887, 3), (0x0DAD088C, 7)]
)
def test_now_playing_indicators_remain_readable(
    osos: bytes, resource_id: int, minimum: float
) -> None:
    locations = stock_resource_locations(osos)
    offset, size = locations["BMap", resource_id]
    data = osos[offset : offset + size]
    if role := bitmap_roles().get(resource_id):
        data = themed_bitmap(resource_id, role, osos, locations)
    pixels = Bitmap.parse(data).rgba()
    opaque = [
        (pixels[i], pixels[i + 1], pixels[i + 2])
        for i in range(0, len(pixels), 4)
        if pixels[i + 3] == 255
    ]
    assert opaque
    assert all(contrast(color, BASE) >= minimum for color in opaque)
    if resource_id == 0x0DAD0887:
        # Unrated stars stay distinguishable from the native white rated stars.
        assert all(contrast(color, (255, 255, 255)) >= 3 for color in opaque)


@pytest.mark.parametrize(
    "resource_id,x,y",
    [
        (0x0DAD018E, 0, 13),  # Now Playing option-bar well.
        (0x0DAD0191, 0, 13),  # Shuffle option-bar thumb.
        (0x0DAD08C0, 15, 16),  # Start Genius drag control, away from the arrow.
        (0x0DAD0199, 5, 13),  # Search input field.
        (0x0DAD071F, 1, 1),  # Album proxy background.
        (0x0DAD0720, 1, 1),  # Artist proxy background.
        (0x0DAD012F, 1, 1),  # No-content album placeholder.
        (0x0DAD0128, 1, 1),  # Large missing-cover placeholder.
        (0x0DAD0129, 1, 1),  # Large empty-library placeholder.
    ],
)
def test_dark_control_and_placeholder_backgrounds(
    osos: bytes, resource_id: int, x: int, y: int
) -> None:
    locations = stock_resource_locations(osos)
    at, size = locations["BMap", resource_id]
    data = osos[at : at + size]
    if role := bitmap_roles().get(resource_id):
        data = themed_bitmap(resource_id, role, osos, locations)
    bitmap = Bitmap.parse(data)
    pixel = (y * bitmap.width + x) * 4
    color = bitmap.rgba()[pixel : pixel + 4]
    assert color[3] == 255
    assert max(color[:3]) <= 180, (hex(resource_id), tuple(color))


def test_dark_control_label_and_embedded_arrow_contrast(osos: bytes) -> None:
    locations = stock_resource_locations(osos)
    for resource_id in (0x0DAD0191, 0x0DAD0199):
        bitmap = Bitmap.parse(
            themed_bitmap(resource_id, bitmap_roles()[resource_id], osos, locations)
        )
        pixels = bitmap.rgba()
        # Flat center of the selected Shuffle thumb and Search text field.
        at = (13 * bitmap.width) * 4
        background = (pixels[at], pixels[at + 1], pixels[at + 2])
        assert contrast(PRIMARY, background) >= 4.5
    resource_id = 0x0DAD08C0
    at, size = locations["BMap", resource_id]
    original = Bitmap.parse(osos[at : at + size]).rgba()
    changed = Bitmap.parse(
        themed_bitmap(resource_id, "genius-thumb", osos, locations)
    ).rgba()
    # Opaque dark arrow pixels become light ink; its original light body becomes
    # blue. Check actual native colors rather than only the theme constants.
    arrow: set[tuple[int, int, int]] = set()
    body: set[tuple[int, int, int]] = set()
    for i in range(0, len(original), 4):
        color = (changed[i], changed[i + 1], changed[i + 2])
        if original[i + 3] == 255:
            if max(original[i : i + 3]) <= 128:
                arrow.add(color)
            elif min(original[i : i + 3]) >= 196:
                body.add(color)
    assert arrow and body
    assert all(contrast(ink, surface) >= 4.5 for ink in arrow for surface in body)
