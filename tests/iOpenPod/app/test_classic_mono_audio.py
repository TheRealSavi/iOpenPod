"""Check Mono Audio composition and the native hooks in the shipped Classic OS."""

import struct

import pytest
from PIL import Image
from scripts.firmware import classic_appearance, classic_mono
from scripts.firmware.classic_bitmaps import Bitmap
from scripts.firmware.classic_menu import included_mods, menu_resources, mod_records
from scripts.firmware.classic_patches import runtime_offset
from scripts.firmware.classic_resources import blocks, u32

from iOpenPod.app.firmware.classic_shared import OSOS_LENGTH_OFFSET, OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware


@pytest.fixture(scope="module")
def osos() -> bytes:
    image = bundled_firmware()
    return image[OSOS_OFFSET : OSOS_OFFSET + u32(image, OSOS_LENGTH_OFFSET)]


@pytest.mark.parametrize("appearance", [False, True])
def test_mono_setting_extends_the_selected_menu(osos: bytes, appearance: bool) -> None:
    options = {"homebrew_eapps": False, "dark_mode": appearance, "mono_audio": True}
    menu = menu_resources(osos, included_mods(**options))
    if appearance:
        classic_appearance.settings_resources(menu)
    before = menu.stock | menu.added
    classic_mono.mono_resources(menu)

    rows = blocks(menu.added["ITEM", 65])
    row_ids = [u32(body, 0x30) for _, body in rows]
    index = row_ids.index(0x0DAD0C76) + 1  # Sound Check
    assert row_ids[index] == classic_mono.ROW
    assert rows[:index] + rows[index + 1 :] == blocks(before["ITEM", 65])
    bindings = blocks(menu.added["SORC", u32(rows[index][1], 0x68)])
    assert menu.added["Str ", u32(bindings[0][1], 4)] == b"Mono Audio\0"
    assert bindings[1][1] == struct.pack("<3I", 0x8900, classic_mono.VALUE, 10)
    events = menu.added["CEVT", 0x0DAD0C6A]
    original = before["CEVT", 0x0DAD0C6A]
    assert u32(events, 0) == u32(original, 0) + 2
    assert events[4 : len(original)] == original[4:]
    assert classic_mono.ACTION.encode() in events[len(original) :]
    assert classic_mono.PREVIEW.encode() in events[len(original) :]
    layouts = blocks(menu.added["SLst", 0x0DAD0C6A])
    assert layouts[:-1] == blocks(before["SLst", 0x0DAD0C6A])
    assert u32(layouts[-1][1], 0) == menu.names[classic_mono.PREVIEW]
    [(_, layout)] = blocks(menu.added["SLyt", menu.names[classic_mono.PREVIEW]])
    instances = blocks(menu.added["SSin", u32(layout, 0)])
    resources = menu.stock | menu.added
    [icon_options] = [
        options
        for _, instance in instances
        for child, options in blocks(
            resources.get(("VLyt", u32(instance, 8)), bytes(4))
        )
        if child == 0x0DAD0C30
    ]
    source = u32(dict(blocks(icon_options))[0x534F5243], 0)
    [(kind, binding)] = blocks(resources["SORC", source])
    service, icon, destination = struct.unpack("<3I", binding)
    assert (kind, service, destination) == (0x534F5243, 0x80, 1)
    assert ("BMap", icon) not in menu.stock
    bitmap = Bitmap.parse(menu.added["BMap", icon])
    with Image.open(classic_mono.ICON_PATH) as image:
        assert image.mode == "L" and image.size == (bitmap.width, bitmap.height)
        assert bitmap.format == 8
        assert bitmap.rgba()[::4] == image.tobytes()
    assert bitmap.data in osos
    assert {record["name"] for record in mod_records(**options)} >= {"Mono Audio"}
    assert "Mono Audio" not in {mod.name for mod in included_mods(homebrew_eapps=False)}


def test_bundled_mixer_hook_comes_after_all_voices(osos: bytes) -> None:
    finish = runtime_offset(0x22007ED0, 8)
    assert u32(osos, finish) == 0xE51FF004
    assert 0x08B3C000 <= u32(osos, finish + 4) < 0x08F3C000
    # The initial and route-switch driver registrations use the same refill.
    for address in (0x220076EC, 0x22008020):
        assert u32(osos, runtime_offset(address, 4)) == 0x22007840
    assert b"iPod_Control\\Device\\iOPMonoAudio\0" in osos
