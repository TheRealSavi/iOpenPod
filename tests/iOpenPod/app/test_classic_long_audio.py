"""Scope and qualification of the two opt-in long-audio firmware repairs."""

import struct

import pytest
from scripts.firmware.classic_menu import included_mods
from scripts.firmware.classic_patches import (
    apply_patches,
    arm_call,
    native_patches,
    runtime_offset,
)
from scripts.firmware.classic_target import INPUT_BYTES

from iOpenPod.app.firmware.classic_layout import MOD_BASE, MOD_MEMORY_BYTES
from iOpenPod.app.firmware.classic_shared import OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware

SYMBOLS = {
    "__payload_limit": 0x08B50000,
    "iop_resource_init": 0x08B3C100,
    "iop_audio_seek": 0x08B3C800,
}
SITES = {0x081BB5E8: 0xE512101C, 0x081BC0F4: 0xE5121014, 0x081BC114: 0xE512101C}


def test_long_audio_hooks_preserve_seek_validation_and_native_vtable() -> None:
    base = tuple(native_patches(SYMBOLS, homebrew_eapps=False, dark_mode=False))
    enabled = tuple(
        native_patches(SYMBOLS, homebrew_eapps=False, dark_mode=False, long_audio=True)
    )
    added = [p for p in enabled if p not in base]
    assert {p.address for p in added} == {*SITES, 0x081BD204}
    raw = bytearray(INPUT_BYTES)
    for patch in enabled:
        at = runtime_offset(patch.address, len(patch.before))
        raw[at : at + len(patch.before)] = patch.before
    patched, records = apply_patches(bytes(raw), enabled)
    assert len(records) == len(enabled)
    for address, instruction in SITES.items():
        at = runtime_offset(address, 4)
        assert raw[at : at + 4] == struct.pack("<I", 0xE1A01FC0)
        assert patched[at : at + 4] == struct.pack("<I", instruction)
    hook = next(p for p in added if p.address == 0x081BD204)
    assert hook.before == arm_call(0x081BD204, 0x081BB188)
    assert hook.after == arm_call(0x081BD204, SYMBOLS["iop_audio_seek"])
    # The native seek vtable and validation/video call remain untouched.
    for address in (0x08994A68, 0x081BD1F0, 0x081BD1DC):
        at = runtime_offset(address, 4)
        assert patched[at : at + 4] == raw[at : at + 4]
    for patch in added:
        corrupt = bytearray(raw)
        corrupt[runtime_offset(patch.address, 4)] ^= 1
        with pytest.raises(ValueError, match="Unexpected instructions/data"):
            apply_patches(bytes(corrupt), enabled)


def test_each_audio_repair_is_visible_in_the_mods_registry() -> None:
    base = included_mods(homebrew_eapps=False)
    enabled = included_mods(homebrew_eapps=False, long_audio=True)
    assert [mod.name for mod in enabled if mod not in base] == [
        "Long Audio Playback",
        "Fast Audio Seeking",
    ]


def test_bundled_release_contains_both_repairs_and_keeps_native_seek_entry() -> None:
    osos = bundled_firmware()[OSOS_OFFSET:]
    for address, instruction in SITES.items():
        assert (
            struct.unpack_from("<I", osos, runtime_offset(address, 4))[0] == instruction
        )
    call = struct.unpack_from("<I", osos, runtime_offset(0x081BD204, 4))[0]
    assert call >> 24 == 0xEB
    displacement = (call & 0xFFFFFF) << 2
    if displacement & (1 << 25):
        displacement -= 1 << 26
    target = 0x081BD204 + 8 + displacement
    assert MOD_BASE <= target < MOD_BASE + MOD_MEMORY_BYTES
    assert (
        struct.unpack_from("<I", osos, runtime_offset(0x08994A68, 4))[0] == 0x081BD1CC
    )
    assert b"Long Audio Playback\0" in osos
    assert b"Fast Audio Seeking\0" in osos
