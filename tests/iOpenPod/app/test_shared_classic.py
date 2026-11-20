"""Common artifacts, migration identity and per-device authentication contracts."""

import hashlib
import json
import struct
from dataclasses import replace
from importlib.resources import files
from threading import Event

import pytest
from tests.iOpenPod.app.test_bootloader import CryptoDfu, Wire, syscfg
from tests.iOpenPod.GUI.test_device_summary_page import summary_active_ipod

from iOpenPod.app.firmware import classic_shared as image
from iOpenPod.app.firmware.bootloader_install import (
    UnlockIdentity,
    supported_identity,
    verify_syscfg,
)
from iOpenPod.app.firmware.bootloader_targets import (
    CLASSIC_BOOTLOADERS,
    BootloaderTarget,
)
from iOpenPod.app.firmware.classic_layout import ClassicFirmwareLayout
from iOpenPod.app.firmware.shared_bootloader import BODY_SHA256, SharedBootloaderBundle


@pytest.mark.parametrize("target", CLASSIC_BOOTLOADERS, ids=lambda t: str(t.family))
def test_shared_os_observation_retains_real_dfu_hardware(
    target: BootloaderTarget,
) -> None:
    active = summary_active_ipod()
    observed = replace(
        active,
        updater_family_id=38,
        firmware_version="2.0.5",
        profile=replace(active.profile, model_number=target.models[0]),
    )
    selected = supported_identity(observed, "windows")
    assert selected is not None and not selected.shared_os
    assert selected.reported_family == 38
    assert selected.reported_version == "2.0.5"
    assert selected.family == (target.family if target.family in (24, 33) else None)
    actual = UnlockIdentity(active.serial_number, target.models[0], target.family)
    assert verify_syscfg(syscfg(actual), selected) == target.family
    with pytest.raises(ValueError, match="does not match"):
        verify_syscfg(syscfg(replace(actual, serial="OTHER123456")), selected)


def test_only_one_shared_output_and_writer_are_bundled() -> None:
    bundle = SharedBootloaderBundle()
    root = files("iOpenPod").joinpath("assets/bootloader/classic-shared")
    manifest = json.loads(root.joinpath("manifest.json").read_bytes())
    assert manifest["target_sha256"] == BODY_SHA256
    assert {s["family"] for s in manifest["sources"]} == {24, 33, 35, 38}
    assert len(manifest["sources"]) == 13  # Four stock, four v1, v5b, four shared v2.
    assert [name for name in manifest["files"] if name.endswith(".dfu")] == [
        "writer.dfu"
    ]
    marker = bytes.fromhex(manifest["marker_hex"])
    assert struct.unpack_from("<4I", marker, 32) == (2, 2, image.IMAGE_TARGET, 15)
    for family in (24, 33, 35, 38):
        with pytest.raises(ValueError, match="qualified source"):
            bundle.apply(bytes(0x1F800), family)


def test_device_authentication_changes_only_header_macs() -> None:
    # Independent hardware-key models show the body is a shared artifact.
    body = bytes(range(256)) * (0x1F800 // 256)
    first, second = CryptoDfu(Wire(), Event()), CryptoDfu(Wire(), Event())
    second.key = bytes(reversed(range(16)))
    a, b = first.seal(body), second.seal(body)
    assert a[0x800:] == b[0x800:] == body
    changed = {i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y}
    assert changed and changed <= set(range(16, 32)) | set(range(64, 80))
    assert a[16:32] != b[16:32] and a[64:80] != b[64:80]
    assert first.plaintext(a) == second.plaintext(b) == body
    with pytest.raises(ValueError, match="authentication"):
        first.plaintext(b)


def test_common_os_is_independent_of_device_and_old_family_tags() -> None:
    raw = image.wrap_shared_os(b"native-os-body")
    image.validate_shared_os(raw)
    assert raw[image.HEADER_BYTES :] == b"native-os-body" + bytes(2)
    assert struct.unpack_from("<II", raw, 24) == (image.IMAGE_TARGET, 2)
    for family in (24, 33, 35, 38):
        bad = bytearray(raw)
        struct.pack_into("<I", bad, 24, family)
        with pytest.raises(ValueError, match="framing"):
            image.validate_shared_os(bytes(bad))


@pytest.mark.parametrize("offset", [0, 7, 8, 12, 16, 20, 28, 32, 48, 64, 68, 2048])
def test_corrupt_shared_image_cannot_be_composed(offset: int) -> None:
    raw = bytearray(image.wrap_shared_os(bytes(16)))
    raw[offset] ^= 1
    with pytest.raises(ValueError):
        image.validate_shared_os(bytes(raw))


def test_full_composition_preserves_resources_and_disables_stock_nor_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Small synthetic firmware layout exercises publication boundaries without
    # distributing Apple firmware. Real input hashes/layouts are audited offline.
    old = ClassicFirmwareLayout(0x6000, 0x8000, 0x8800, 0x9000)
    new = ClassicFirmwareLayout(0x6000, 0xB000, 0xB800, 0xC000)
    data = bytearray(bytes(range(256)) * 144)
    struct.pack_into("<I", data, 0x505C, old.aupd)
    struct.pack_into("<I", data, 0x5084, old.hash_record)
    stock = bytes(data)
    monkeypatch.setattr(image, "STOCK_LAYOUT", old)
    monkeypatch.setattr(image, "EXPANDED_LAYOUT", new)
    monkeypatch.setattr(image, "FIRMWARE_SHA256", hashlib.sha256(stock).hexdigest())
    osos = image.wrap_shared_os(bytes(range(32)))
    result = image.compose_shared_firmware(stock, osos)
    assert len(result) == new.end
    assert result[0x6000 : 0x6000 + len(osos)] == osos
    assert result[0x6000 + len(osos) : new.aupd] == bytes(new.os_slot_bytes - len(osos))
    assert result[new.aupd :] == stock[old.aupd :]
    assert struct.unpack_from("<I", result, 0x5038)[0] == len(osos)
    assert struct.unpack_from("<I", result, 0x5058)[0] == 1
    assert struct.unpack_from("<I", result, 0x505C)[0] == new.aupd
    assert struct.unpack_from("<I", result, 0x5084)[0] == new.hash_record
    masked = bytearray(result[: old.osos])
    for start, end in ((0x5038, 0x503C), (0x5058, 0x5060), (0x5084, 0x5088)):
        masked[start:end] = stock[start:end]
    assert bytes(masked) == stock[: old.osos]
    with pytest.raises(ValueError, match="pinned original"):
        image.compose_shared_firmware(stock[:-1], osos)


def test_live_partition_capacity_is_required() -> None:
    image.require_firmware_capacity(192 * 1024 * 1024)
    for size in (0, True, image.FIRMWARE_BYTES - 1, 512 * 1024 * 1024):
        with pytest.raises(ValueError, match="observed firmware partition"):
            image.require_firmware_capacity(size)


def test_shared_os_expanded_bound_accepts_large_mods_but_not_overflow() -> None:
    # Exercise the actual host format at the loader limit, not a reduced mock.
    wrapped = image.wrap_shared_os(bytes(image.MAX_BODY_BYTES))
    image.validate_shared_os(wrapped)
    assert len(wrapped) == 16 * 1024 * 1024
    assert image.MAX_BODY_BYTES > 10634496 + 4 * 1024 * 1024
    for size in (0, image.MAX_BODY_BYTES + 1):
        with pytest.raises(ValueError, match="image bound"):
            image.wrap_shared_os(bytes(size))
