"""Validate the native menu graph against the bundled Apple 2.0.5 resources."""

import struct

import pytest
from PIL import Image
from scripts.firmware.classic_bitmaps import Bitmap
from scripts.firmware.classic_menu import (
    EXTRAS_ITEMS,
    EXTRAS_SCREEN,
    MOD_ENTRY,
    MOD_ITEMS,
    MOD_LAYOUT,
    MOD_LAYOUT_NAME,
    MOD_PREVIEW_IMAGE,
    MOD_PREVIEW_NAME,
    MOD_SCREEN,
    MOD_SCREEN_NAME,
    MenuResources,
    emit_menu_header,
    included_mods,
    menu_resources,
    mod_records,
)
from scripts.firmware.classic_resources import RESOURCE_SCRATCH_BYTES, blocks, u32

from iOpenPod.app.firmware.classic_shared import OSOS_LENGTH_OFFSET, OSOS_OFFSET
from iOpenPod.app.firmware.shared_release import bundled_firmware


@pytest.fixture(scope="module")
def osos() -> bytes:
    image = bundled_firmware()
    size = u32(image, OSOS_LENGTH_OFFSET)
    return image[OSOS_OFFSET : OSOS_OFFSET + size]


@pytest.fixture(scope="module")
def menu(osos: bytes) -> MenuResources:
    return menu_resources(osos, included_mods(homebrew_eapps=True))


def source_text(menu: MenuResources, source: int) -> str:
    bindings = blocks(menu.added["SORC", source])
    assert len(bindings) == 1
    kind, body = bindings[0]
    assert kind == 0x534F5243
    mode, string_id, destination = struct.unpack("<3I", body)
    assert (mode, destination) == (0x80, 1)
    return menu.added["Str ", string_id].removesuffix(b"\0").decode()


def parse_events(data: bytes) -> dict[str, list[tuple[str, list[str]]]]:
    """Independent reader: consume complete variable-length native event streams."""
    position = 4

    def integer() -> int:
        nonlocal position
        value = u32(data, position)
        position += 4
        return value

    def string() -> str:
        nonlocal position
        size = integer()
        value = data[position : position + size].decode()
        position += size
        return value

    events: dict[str, list[tuple[str, list[str]]]] = {}
    for _ in range(u32(data, 0)):
        name = string()
        assert data[position : position + 1] in (b"0", b"1")
        position += 1
        string()  # Optional controller handler.
        actions: list[tuple[str, list[str]]] = []
        for _ in range(integer()):
            action = string()
            arguments = [string() for _ in range(integer())]
            actions.append((action, arguments))
        assert name not in events
        events[name] = actions
    assert position == len(data)
    return events


def test_extras_keeps_original_entries_and_routes_to_mods(menu: MenuResources) -> None:
    original = blocks(menu.stock["ITEM", EXTRAS_ITEMS])
    updated = blocks(menu.added["ITEM", EXTRAS_ITEMS])
    assert updated[:-1] == original
    row = updated[-1][1]
    assert u32(row, 0x30) == MOD_ENTRY
    assert row[0x64] == 1  # Visible without a user preference.
    assert u32(row, 0x60) == 5  # Native submenu arrow.
    assert source_text(menu, u32(row, 0x68)) == "Mods"
    old_events = parse_events(menu.stock["CEVT", EXTRAS_SCREEN])
    events = parse_events(menu.added["CEVT", EXTRAS_SCREEN])
    assert events.items() >= old_events.items()
    assert len(events) == len(old_events) + 2
    assert events[f"list.pid.{MOD_ENTRY}.chosen"] == [
        ("navigator.PushScreen", [MOD_SCREEN_NAME, MOD_LAYOUT_NAME, "foregroundpush"])
    ]
    assert events[f"list.pid.{MOD_ENTRY}.delayedselected"] == [
        ("navigator.SwitchLayout", [MOD_PREVIEW_NAME])
    ]
    games_event = b"list.pid.229442001.delayedselected"
    mods_event = f"list.pid.{MOD_ENTRY}.delayedselected".encode()
    assert games_event + b"0" in menu.stock["CEVT", EXTRAS_SCREEN]
    assert mods_event + b"0" in menu.added["CEVT", EXTRAS_SCREEN]


def test_highlighting_mods_resolves_its_own_gear_in_the_games_frame(
    menu: MenuResources,
) -> None:
    preview = menu.names[MOD_PREVIEW_NAME]
    variants = blocks(menu.added["SLst", EXTRAS_SCREEN])
    assert variants[:-1] == blocks(menu.stock["SLst", EXTRAS_SCREEN])
    assert u32(variants[-1][1], 0) == preview
    games = 0x0DAD01DC
    assert menu.added["SEVT", preview] == menu.stock["SEVT", games]
    [(_, layout)] = blocks(menu.added["SLyt", preview])
    instances = blocks(menu.added["SSin", u32(layout, 0)])
    [(_, stock_layout)] = blocks(menu.stock["SLyt", games])
    stock_instances = blocks(menu.stock["SSin", u32(stock_layout, 0)])
    assert len(instances) == len(stock_instances) == 4
    for (_, current), (_, original) in zip(instances, stock_instances, strict=True):
        new_id, old_id = u32(current, 0), u32(original, 0)
        assert new_id != old_id
        for binding in ("VCrv", "VCvs"):
            assert menu.added.get((binding, new_id)) == menu.stock.get(
                (binding, old_id)
            )
        assert current[4:8] == original[4:8]
        assert current[12:] == original[12:]
    assert [v[8:12] for _, v in instances[:-1]] == [
        v[8:12] for _, v in stock_instances[:-1]
    ]
    template = u32(instances[-1][1], 4)
    # On a ROM bank the native template/child iterators visit only directory IDs.
    assert ("TMLT", template) in menu.stock
    stock_children = blocks(menu.stock["View", template])
    children = blocks(menu.added["View", template])
    assert children[:-1] == stock_children
    (kind, view) = children[-1]
    dice = dict(stock_children)[kind]
    gear_child = u32(view, 0x30)
    assert kind == 0x696D6167 and gear_child != u32(dice, 0x30)
    for last, visible in ((stock_instances[-1][1], False), (instances[-1][1], True)):
        options = dict(blocks(menu.added["VLyt", u32(last, 8)]))
        for _, child in children:
            child_id = u32(child, 0x30)
            assert dict(blocks(options[child_id]))[1005] == bytes(
                [(child_id == gear_child) == visible]
            )
    assert (
        view[:0x30] + view[0x34:0x74] + view[0x78:]
        == dice[:0x30] + dice[0x34:0x74] + dice[0x78:]
    )
    [(source_kind, source)] = blocks(menu.added["SORC", u32(view, 0x74)])
    service, image_id, destination = struct.unpack("<3I", source)
    assert (source_kind, service, destination) == (0x534F5243, 0x80, 1)
    bitmap_id = u32(menu.added["IMAG", image_id], 0)
    gear = Bitmap.parse(menu.added["BMap", bitmap_id])
    with Image.open(MOD_PREVIEW_IMAGE) as image:
        assert (gear.width, gear.height) == image.size == (142, 87)
        assert gear.rgba() == image.convert("RGBA").tobytes()


@pytest.mark.parametrize("homebrew", [True, False])
def test_menu_lists_only_included_mods(osos: bytes, homebrew: bool) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=homebrew))
    rows = blocks(menu.added["ITEM", MOD_ITEMS])
    names = [source_text(menu, u32(body, 0x68)) for _, body in rows]
    expected = ["Mod Version String", "Mod Version in About"]
    if homebrew:
        expected.append("Unsigned Game Manifests")
    expected.extend(("Mod Menu", "Expanded Mod Memory"))
    assert names == expected
    assert names == [record["name"] for record in mod_records(homebrew_eapps=homebrew)]
    assert all(u32(row, 0x60) == 2 and row[0x64] == 1 for _, row in rows)
    assert len({u32(row, 0x30) for _, row in rows}) == len(rows)
    assert parse_events(menu.added["CEVT", MOD_SCREEN]) == {}


def test_layout_reuses_native_views_and_binds_new_title_and_rows(
    menu: MenuResources,
) -> None:
    assert menu.added["SCST", MOD_SCREEN] == menu.stock["SCST", 0x0DAD0C6A]
    layouts = blocks(menu.added["SLst", MOD_SCREEN])
    assert len(layouts) == 1 and u32(layouts[0][1], 0) == MOD_LAYOUT
    titles: list[str] = []
    tables: list[int] = []
    for _, layout in blocks(menu.added["SLyt", MOD_LAYOUT]):
        for _, instance in blocks(menu.added["SSin", u32(layout, 0)]):
            assert ("View", u32(instance, 4)) in menu.stock
            assert ("VLyt", u32(instance, 8)) in menu.stock
            for target, body in blocks(menu.added["VCvs", u32(instance, 0)]):
                if target == 0x0DAD01A6:
                    titles.append(source_text(menu, u32(body, 12)))
                elif target == 0x3F1:
                    tables.append(u32(body, 4))
                else:
                    pytest.fail(f"Unexpected list binding: {target:x}")
    assert titles == ["Mods"] and tables == [MOD_ITEMS]
    assert parse_events(menu.added["SEVT", MOD_LAYOUT]) == {
        "button.menu.up": [("navigator.PopTopScreen", [])],
        "button.menu.pressandhold": [("navigator.PopToMainScreen", [])],
    }
    assert menu.added.keys() & menu.stock.keys() == {
        ("ITEM", EXTRAS_ITEMS),
        ("CEVT", EXTRAS_SCREEN),
        ("SLst", EXTRAS_SCREEN),
        ("View", 0x0DAD019C),
    }


def test_emitter_rejects_invalid_extension(osos: bytes) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=True))
    bad = bytearray(menu.added["ITEM", EXTRAS_ITEMS])
    bad[50] ^= 1
    menu.added["ITEM", EXTRAS_ITEMS] = bytes(bad)
    with pytest.raises(ValueError, match="preserve the complete stock prefix"):
        emit_menu_header(menu, osos)


def test_emitter_uses_directory_even_when_source_bytes_are_duplicated(
    osos: bytes,
) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=True))
    duplicated = osos + menu.stock["ITEM", EXTRAS_ITEMS]
    assert emit_menu_header(menu, duplicated) == emit_menu_header(menu, osos)


def test_emitter_rejects_extension_larger_than_native_workspace(osos: bytes) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=True))
    key = "ITEM", EXTRAS_ITEMS
    extension = menu.added[key]
    menu.added[key] = extension + bytes(RESOURCE_SCRATCH_BYTES + 1 - len(extension))
    with pytest.raises(ValueError, match="exceeds reserved initialization workspace"):
        emit_menu_header(menu, osos)


def test_emitter_rejects_source_that_disagrees_with_directory(osos: bytes) -> None:
    menu = menu_resources(osos, included_mods(homebrew_eapps=True))
    key = "ITEM", EXTRAS_ITEMS
    # Preserve the extension's prefix contract but corrupt the assumed source.
    for mapping in (menu.stock, menu.added):
        corrupted = bytearray(mapping[key])
        corrupted[50] ^= 1
        mapping[key] = bytes(corrupted)
    with pytest.raises(ValueError, match="differs from its native directory entry"):
        emit_menu_header(menu, osos)


@pytest.mark.parametrize("data", [b"", struct.pack("<I", 1), b"\0" * 5])
def test_block_reader_rejects_incomplete_resources(data: bytes) -> None:
    with pytest.raises(ValueError):
        blocks(data)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("dark_mode", [False, True])
def test_preview_artwork_mod_is_independent_and_listed_when_included(
    osos: bytes, enabled: bool, dark_mode: bool
) -> None:
    mods = included_mods(
        homebrew_eapps=True,
        dark_mode=dark_mode,
        now_playing_artwork=enabled,
    )
    menu = menu_resources(osos, mods)
    names = [
        source_text(menu, u32(row, 0x68))
        for _, row in blocks(menu.added["ITEM", MOD_ITEMS])
    ]
    assert ("Now Playing Preview Artwork" in names) is enabled
    assert names == [
        record["name"]
        for record in mod_records(
            homebrew_eapps=True,
            dark_mode=dark_mode,
            now_playing_artwork=enabled,
        )
    ]
    assert ("Light / Dark Appearance" in names) is dark_mode
