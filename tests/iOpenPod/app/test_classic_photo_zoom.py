"""Verify the opt-in photo hooks and the firmware shipped by the installer."""

import struct

from scripts.firmware.classic_menu import included_mods, serialized_string
from scripts.firmware.classic_patches import arm_call, native_patches, runtime_offset
from scripts.firmware.classic_resources import stock_resources

from iOpenPod.app.firmware.classic_layout import MOD_BASE, MOD_MEMORY_BYTES
from iOpenPod.app.firmware.classic_shared import OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware

SITES = {
    0x089956D0: "iop_photo_event",
    0x0899FE8C: "iop_photo_event",
    0x08995724: "iop_photo_timer",
    0x081C2388: "iop_photo_open_large",
    0x081C1350: "iop_photo_leave",
    0x081002E4: "iop_photo_blit",
}
CACHE_SITE = 0x081C23BC


def test_photo_mod_owns_only_its_selected_hooks_and_menu_row() -> None:
    symbols = {"__payload_limit": MOD_BASE + 0x1000, "iop_resource_init": MOD_BASE}
    symbols.update({name: MOD_BASE + i * 4 for i, name in enumerate(SITES.values(), 1)})
    normal = tuple(native_patches(symbols, homebrew_eapps=False, dark_mode=False))
    zoom = tuple(
        native_patches(symbols, homebrew_eapps=False, dark_mode=False, photo_zoom=True)
    )
    assert {patch.address for patch in zoom if patch not in normal} == {
        *SITES,
        CACHE_SITE,
    }
    cache_patch = next(patch for patch in zoom if patch.address == CACHE_SITE)
    assert cache_patch.before == struct.pack("<I", 0xE3E02000)
    assert cache_patch.after == struct.pack("<I", 0xE3A02005)
    assert all(patch in zoom for patch in normal)
    mods = included_mods(homebrew_eapps=False, photo_zoom=True)
    assert mods[:-1] == included_mods(homebrew_eapps=False)
    assert (mods[-1].id, mods[-1].name, mods[-1].version) == (
        "org.iopenpod.photo-zoom",
        "Photo Zoom and Pan",
        "0.3.0-dev",
    )


def test_release_routes_photos_to_mod_and_preserves_slideshow_binding() -> None:
    osos = bundled_firmware()[OSOS_OFFSET:]
    assert b"Photo Zoom and Pan\0" in osos
    assert (
        struct.unpack_from("<I", osos, runtime_offset(CACHE_SITE, 4))[0] == 0xE3A02005
    )
    targets: dict[str, int] = {}
    for address, name in SITES.items():
        value = struct.unpack_from("<I", osos, runtime_offset(address, 4))[0]
        if name in ("iop_photo_open_large", "iop_photo_leave", "iop_photo_blit"):
            assert value >> 24 == (0xEA if name == "iop_photo_leave" else 0xEB)
            displacement = (value & 0xFFFFFF) << 2
            if displacement & (1 << 25):
                displacement -= 1 << 26
            value = address + 8 + displacement
        assert MOD_BASE <= value < MOD_BASE + MOD_MEMORY_BYTES
        assert targets.setdefault(name, value) == value
    assert len(set(targets.values())) == len(targets)
    # The standalone ImageView hooked by 0.8.1-dev belongs to a different screen.
    other_view = 0x080F76C4
    offset = runtime_offset(other_view, 4)
    assert osos[offset : offset + 4] == arm_call(other_view, 0x08259568)
    large = stock_resources(osos)["SEVT", 0x0DAD0A58]
    assert (
        serialized_string("button.playpause.up")
        + b"1"
        + serialized_string("HandleBrowseSlideshow")
        + struct.pack("<I", 0)
    ) in large
