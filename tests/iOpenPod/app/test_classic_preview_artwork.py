"""Qualify the preview binding against the actual bundled Classic UI resources."""

import struct
from pathlib import Path

import pytest
from scripts.firmware.build_classic import build
from scripts.firmware.classic_appearance import settings_resources
from scripts.firmware.classic_menu import MenuResources, included_mods, menu_resources
from scripts.firmware.classic_patches import (
    apply_patches,
    arm_call,
    native_patches,
    runtime_offset,
)
from scripts.firmware.classic_preview_artwork import preview_artwork_resources
from scripts.firmware.classic_resources import blocks, u32

from iOpenPod.app.firmware.classic_shared import OSOS_LENGTH_OFFSET, OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware


@pytest.fixture(scope="module")
def osos() -> bytes:
    image = bundled_firmware()
    return image[OSOS_OFFSET : OSOS_OFFSET + u32(image, OSOS_LENGTH_OFFSET)]


def compose(osos: bytes) -> MenuResources:
    return menu_resources(
        osos,
        included_mods(homebrew_eapps=True, now_playing_artwork=True),
    )


def test_bundled_release_keeps_preview_fixes_without_artwork_tracing(
    osos: bytes,
) -> None:
    # Photo Zoom uses the untiled BitmapView blit at 0x081002e4. Its release
    # hook is checked in test_classic_photo_zoom. These tracing sites stay stock.
    original_hooks = {
        0x08988974: struct.pack("<I", 0x0810012C),
        0x0810008C: arm_call(0x0810008C, 0x08268B64),
        0x08100278: arm_call(0x08100278, 0x08259568),
    }
    for address, original in original_hooks.items():
        offset = runtime_offset(address, 4)
        assert osos[offset : offset + 4] == original
    for address, original in (
        (0x081001F0, bytes.fromhex("b80bd4e1")),
        (0x08998708, struct.pack("<I", 0x081EDA2C)),
        (0x089889A8, struct.pack("<I", 0x08100318)),
    ):
        offset = runtime_offset(address, 4)
        assert osos[offset : offset + 4] != original
    assert b"iOpenPodArtworkTrace" not in osos
    assert b"iOpenPodBootReport" in osos


def test_preview_hooks_are_optional_and_reject_foreign_preimages(
    osos: bytes,
) -> None:
    symbols = {
        "__payload_limit": 0x08B58000,
        "iop_resource_init": 0x08B3C100,
        "iop_artwork_visibility": 0x08B3C200,
        "iop_artwork_property": 0x08B3C300,
        "iop_artwork_format": 0x08B3C400,
    }
    without = list(native_patches(symbols, homebrew_eapps=False, dark_mode=False))
    with_artwork = list(
        native_patches(
            symbols,
            homebrew_eapps=False,
            dark_mode=False,
            now_playing_artwork=True,
        )
    )
    extra = [patch for patch in with_artwork if patch not in without]
    assert len(extra) == 3
    expected = {
        0x081001F0: (
            bytes.fromhex("b80bd4e1"),
            arm_call(0x081001F0, symbols["iop_artwork_format"]),
        ),
        0x089889A8: (
            struct.pack("<I", 0x08100318),
            struct.pack("<I", symbols["iop_artwork_visibility"]),
        ),
        0x08998708: (
            struct.pack("<I", 0x081EDA2C),
            struct.pack("<I", symbols["iop_artwork_property"]),
        ),
    }
    assert {hook.address for hook in extra} == expected.keys()
    for hook in extra:
        before, after = expected[hook.address]
        assert hook.before == before
        assert hook.after == after
        # Reconstitute each qualified preimage; the bundled image may already
        # contain the hook. Every other byte must remain identical.
        offset = runtime_offset(hook.address, 4)
        original = bytearray(osos)
        original[offset : offset + 4] = hook.before
        patched, _ = apply_patches(bytes(original), [hook])
        assert patched[:offset] == original[:offset]
        assert patched[offset + 4 :] == original[offset + 4 :]
        original[offset] ^= 1
        with pytest.raises(ValueError, match="Unexpected instructions/data"):
            apply_patches(bytes(original), [hook])


@pytest.mark.parametrize(
    "artwork,report", [(False, False), (True, False), (False, True)]
)
def test_diagnostics_require_artwork_and_a_live_report(
    tmp_path: Path, artwork: bool, report: bool
) -> None:
    with pytest.raises(ValueError, match="Artwork diagnostics require"):
        build(
            tmp_path / "unused.bin",
            tmp_path,
            tmp_path / "unused.exe",
            "0.6.4-diag",
            now_playing_artwork=artwork,
            bootloader_report=report,
            artwork_diagnostics=True,
        )


def test_diagnostic_hooks_are_optional_and_verify_native_preimages(osos: bytes) -> None:
    symbols = {
        "__payload_limit": 0x08B58000,
        "iop_resource_init": 0x08B3C100,
        "iop_artwork_visibility": 0x08B3C200,
        "iop_boot_report_xml": 0x08B3C300,
        "iop_artwork_trace_paint": 0x08B3C400,
        "iop_artwork_trace_query": 0x08B3C500,
        "iop_artwork_trace_blit": 0x08B3C600,
        "iop_artwork_property": 0x08B3C700,
        "iop_artwork_format": 0x08B3C800,
    }
    normal = list(
        native_patches(
            symbols,
            homebrew_eapps=False,
            dark_mode=False,
            now_playing_artwork=True,
            bootloader_report=True,
        )
    )
    debug = list(
        native_patches(
            symbols,
            homebrew_eapps=False,
            dark_mode=False,
            now_playing_artwork=True,
            bootloader_report=True,
            artwork_diagnostics=True,
        )
    )
    hooks = [patch for patch in debug if patch not in normal]
    assert {patch.address for patch in hooks} == {
        0x08988974,
        0x0810008C,
        0x08100278,
        0x081002E4,
    }
    for patch in hooks:
        offset = runtime_offset(patch.address, len(patch.before))
        original = bytearray(osos)
        original[offset : offset + len(patch.before)] = patch.before
        changed, _ = apply_patches(bytes(original), [patch])
        assert changed[:offset] == original[:offset]
        assert (
            changed[offset + len(patch.before) :]
            == original[offset + len(patch.before) :]
        )
        original[offset] ^= 1
        with pytest.raises(ValueError, match="Unexpected instructions/data"):
            apply_patches(bytes(original), [patch])


@pytest.mark.parametrize("dark_mode", [False, True])
def test_only_the_preview_image_source_changes(osos: bytes, dark_mode: bool) -> None:
    menu = compose(osos)
    if dark_mode:
        settings_resources(menu)
    before = menu.added.copy()
    preview_artwork_resources(menu)
    assert menu.added.keys() - before.keys() == {
        ("VCvs", 0x162),
        ("VLyt", 0x0DAD01C0),
    }
    assert all(menu.added[key] == value for key, value in before.items())
    old = menu.stock["VCvs", 0x162]
    new = menu.added["VCvs", 0x162]
    assert len(old) == len(new) == 100
    assert new[:24] == old[:24] and new[28:] == old[28:]
    assert u32(old, 24) == 0x3B1 and u32(new, 24) == 0x4A9
    assert ("VCvs", 0x162) in menu.replacements
    children = blocks(new)
    assert children[0][0] == 0x0DAD01BA
    assert children[1:] == blocks(old)[1:]  # Title, artist and album bindings.
    source = blocks(menu.stock["SORC", u32(children[0][1], 12)])
    assert source == [(0x534F5243, struct.pack("<3I", 0x7F00, 0x7F05, 1))]


@pytest.mark.parametrize(
    "kind,resource_id", [("VCvs", 0x162), ("SORC", 0x4A9), ("VLyt", 0x0DAD01C0)]
)
def test_foreign_native_resources_are_rejected(
    osos: bytes, kind: str, resource_id: int
) -> None:
    menu = compose(osos)
    original = menu.stock[kind, resource_id]
    menu.stock[kind, resource_id] = original[:-1] + bytes((original[-1] ^ 1,))
    with pytest.raises(ValueError, match="Unexpected native Now Playing"):
        preview_artwork_resources(menu)
    assert ("VCvs", 0x162) not in menu.added
    assert ("VLyt", 0x0DAD01C0) not in menu.added


def test_conflicting_override_is_rejected(osos: bytes) -> None:
    menu = compose(osos)
    preview_artwork_resources(menu)
    first = menu.added["VCvs", 0x162]
    with pytest.raises(ValueError, match="already has a resource override"):
        preview_artwork_resources(menu)
    assert menu.added["VCvs", 0x162] == first


def test_native_size_art_fits_above_unchanged_metadata(osos: bytes) -> None:
    menu = compose(osos)
    preview_artwork_resources(menu)
    original = blocks(menu.stock["VLyt", 0x0DAD01C0])
    changed = blocks(menu.added["VLyt", 0x0DAD01C0])
    assert changed[1:] == original[1:]  # All three text layouts stay byte exact.
    assert changed[0][0] == original[0][0] == 0x0DAD01BA
    options = dict(blocks(changed[0][1]))
    assert options[1005] == b"\1"  # Visible.
    top, left, bottom_offset, right_offset = (
        struct.unpack("<iII", options[kind])[0] for kind in range(1000, 1004)
    )
    assert (top, left, bottom_offset + 240, right_offset + 320) == (
        35,
        176,
        163,
        304,
    )
    assert bottom_offset + 240 - top == right_offset + 320 - left == 128
    title_options = dict(blocks(changed[1][1]))
    assert struct.unpack("<iII", title_options[1000])[0] == 170
    # Qualify the resource's sole owner; no other preview layout is modified.
    owners = [
        (resource_id, u32(instance, 0), u32(instance, 4))
        for (kind, resource_id), data in menu.stock.items()
        if kind == "SSin"
        for _, instance in blocks(data)
        if len(instance) >= 12 and u32(instance, 8) == 0x0DAD01C0
    ]
    assert owners == [(0x74, 0x162, 0x0DAD01B9)]
