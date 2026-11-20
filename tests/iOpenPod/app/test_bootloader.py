"""Bootloader format, DFU boundaries and ambiguous write completion without USB."""

import hashlib
import json
import struct
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from threading import Event
from typing import Literal, Protocol, cast

import pytest
from Crypto.Cipher import AES
from tests.iOpenPod.GUI.test_device_summary_page import summary_active_ipod

from iOpenPod.app.firmware import bootloader_probes as probes
from iOpenPod.app.firmware.bootloader_bundle import BootloaderBundle, WriterPlan
from iOpenPod.app.firmware.bootloader_dfu import ClassicBootDfu, verify_report
from iOpenPod.app.firmware.bootloader_install import (
    UnlockIdentity,
    supported_identity,
    verify_syscfg,
)
from iOpenPod.app.firmware.bootloader_targets import (
    CLASSIC_BOOTLOADERS,
    BootloaderTarget,
    bootloader_target,
)
from storage import UsbControlError, UsbControlRequest, UsbControlResponse


class _CbcCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _CbcFactory(Protocol):
    def __call__(self, key: bytes, mode: Literal[2], *, iv: bytes) -> _CbcCipher: ...


# As in iPodDB's signature tests, isolate PyCryptodome's unrelated, untyped CTR
# overload. This adapter exposes only the fully typed CBC interface used here.
_AES_CBC = cast("_CbcFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]


def syscfg(identity: UnlockIdentity) -> bytes:
    assert identity.family is not None
    fields = {
        "SrNm": identity.serial.encode(),
        "Mod#": identity.model.encode(),
        "HwVr": struct.pack("<II", 0, bootloader_target(identity.family).hardware),
    }
    result = struct.pack(
        "<6I", 0x53436667, 24 + len(fields) * 20, 8192, 0x10001, 0, len(fields)
    )
    return (
        result
        + b"".join(
            key.encode()[::-1] + value.ljust(16, b"\0") for key, value in fields.items()
        )
    ).ljust(8192, b"\0")


def report(plan: WriterPlan) -> bytes:
    result = bytearray(256)
    struct.pack_into("<6I", result, 0, 0x314E5249, 1, 6, 0, 4096, 0x20000)
    result[32:48] = plan.nonce
    struct.pack_into("<3I", result, 64, 0xBF258E, 1, 32)
    for offset, digest in (
        (84, plan.before_sha),
        (116, plan.target_sha),
        (148, plan.after_sha),
        (180, plan.outside_sha),
    ):
        result[offset : offset + 32] = bytes.fromhex(digest)
    return bytes(result)


PLAN = WriterPlan(
    bytes(range(16)),
    "11" * 32,
    "22" * 32,
    "33" * 32,
    "44" * 32,
    b"87021.0\x03" + bytes(2040),
)


def test_exact_supported_model_and_selected_identity() -> None:
    active = summary_active_ipod()
    identity = supported_identity(active, "windows")
    assert identity is not None
    verify_syscfg(syscfg(identity), identity)
    with pytest.raises(ValueError, match="does not match"):
        verify_syscfg(syscfg(identity), UnlockIdentity("OTHER123456", "MB565"))
    for platform in ("linux", "macos"):
        assert supported_identity(active, platform) is None
    assert (
        supported_identity(replace(active, serial_number="../../host"), "windows")
        is None
    )
    for changed in (
        replace(active, updater_family_id=29),
        replace(active, updater_family_id=None),
        replace(active, firmware_version="9.9.9-custom"),
        replace(active, firmware_version=""),
    ):
        selected = supported_identity(changed, "windows")
        assert selected is not None and selected.family == 33


@pytest.mark.parametrize(
    "target", CLASSIC_BOOTLOADERS, ids=lambda target: str(target.family)
)
def test_hardware_selection_is_independent_of_os_reports(
    target: BootloaderTarget,
) -> None:
    active = summary_active_ipod()
    for model in target.models:
        selected = replace(
            active,
            profile=replace(active.profile, model_number=model),
            updater_family_id=38,
            firmware_version="9.9.9-custom",
        )
        identity = supported_identity(selected, "windows")
        assert identity is not None
        assert identity == UnlockIdentity(
            active.serial_number,
            model,
            target.family if target.family in (24, 33) else None,
            reported_family=38,
            reported_version="9.9.9-custom",
        )
        actual = UnlockIdentity(active.serial_number, model, target.family)
        assert verify_syscfg(syscfg(actual), identity) == target.family
        if target.family in (35, 38):
            other = 38 if target.family == 35 else 35
            with pytest.raises(ValueError, match="does not match"):
                verify_syscfg(syscfg(actual), replace(identity, family=other))


@pytest.mark.parametrize(
    "target", CLASSIC_BOOTLOADERS, ids=lambda target: str(target.family)
)
def test_each_bundled_manifest_marker_and_writer_match_exact_target(
    target: BootloaderTarget,
) -> None:
    bundle = BootloaderBundle(target.family)
    assert bundle.target is target
    root = files("iOpenPod").joinpath(f"assets/bootloader/classic{target.family}")
    manifest = json.loads(root.joinpath("manifest.json").read_bytes())
    marker = bytes.fromhex(manifest["marker_hex"])
    assert struct.unpack_from("<4I", marker, 32) == (
        1,
        1,
        target.family,
        target.hardware,
    )
    assert manifest["stock_sha256"] == target.stock_sha256
    assert manifest["max_body_bytes"] == target.max_body_bytes
    assert manifest["marker_offset"] + len(marker) == target.gap_start
    assert (
        manifest["slots"]["packed_body"]["size"]
        == target.gap_start + 0x1F800 - target.seccore_offset
    )
    assert root.joinpath("NOTICE.txt").is_file()
    with pytest.raises(ValueError, match="qualified"):
        bundle.apply(bytes(0x1F800))


@pytest.mark.parametrize("family", (24, 33, 35, 38))
def test_writer_reconstructs_the_full_target_with_each_fixed_seccore_tail(
    family: int,
) -> None:
    bundle = BootloaderBundle(family)
    profile = bundle.target
    body = bytearray(bytes(range(256)) * (0x1F800 // 256))
    body[profile.gap_start : profile.seccore_offset] = b"\xff" * (
        profile.seccore_offset - profile.gap_start
    )
    # Synthetic source isolates packing from hardware authentication; actual
    # Apple inputs are exercised by the offline build audit, never CI fixtures.
    bundle.target = replace(profile, target_sha256=hashlib.sha256(body).hexdigest())
    header = b"87021.0\x02" + bytes(0x800 - 8)
    before = bytes(0x100000)
    sealed = header + body
    plan = bundle.writer(before, sealed, bytes(range(16)))
    manifest = json.loads(
        files("iOpenPod")
        .joinpath(f"assets/bootloader/classic{family}/manifest.json")
        .read_bytes()
    )
    slot = manifest["slots"]["packed_body"]
    packed = plan.image[slot["offset"] : slot["offset"] + slot["size"]]
    unpacked = (
        packed[: profile.gap_start]
        + b"\xff" * (profile.seccore_offset - profile.gap_start)
        + packed[profile.gap_start :]
    )
    assert unpacked == body
    assert (
        plan.after_sha
        == hashlib.sha256(before[:0x8000] + sealed + before[0x28000:]).hexdigest()
    )
    assert (
        plan.outside_sha
        == hashlib.sha256(before[:0x8000] + before[0x28000:]).hexdigest()
    )


def test_probes_match_independently_generated_lab_vectors() -> None:
    fixture = Path(__file__).parents[2] / "fixtures/firmware/bootloader-probes.json"
    vectors = json.loads(fixture.read_bytes())
    for vector in vectors["cases"]:
        group, address, size = vector["group"], vector["address"], vector["size"]
        if group == "rom_fingerprint_memory_read64":
            code = probes.memory(address, fast=False)
        elif group == "fast_bootrom512":
            code = probes.memory(0x20000000 + address, 512)
        elif group in ("fast_nor512_primary", "fast_nor_source_shifted509"):
            code = probes.nor_read(address, size)
        elif group == "nor_init":
            code = probes.nor_init()
        else:
            code = probes.memory(address, size)
        assert code.hex() == vector["code_hex"], group


@pytest.mark.parametrize(
    "offset", [0, 4, 8, 12, 16, 20, 32, 64, 68, 72, 84, 116, 148, 180]
)
def test_nonce_and_all_readback_postconditions_are_required(offset: int) -> None:
    verify_report(report(PLAN), PLAN)
    damaged = bytearray(report(PLAN))
    damaged[offset] ^= 1
    with pytest.raises(ValueError):
        verify_report(bytes(damaged), PLAN)


def test_marker_alone_never_qualifies_an_image() -> None:
    bundle = BootloaderBundle()
    fake = bytearray(0x1F800)
    fake[0x1ACC8 : 0x1ACC8 + 21] = b"iOpenPod-Bootloader-v1\0"
    with pytest.raises(ValueError, match="qualified"):
        bundle.apply(bytes(fake))
    manifest = json.loads(
        files("iOpenPod")
        .joinpath("assets/bootloader/classic33/manifest.json")
        .read_bytes()
    )
    marker = bytes.fromhex(manifest["marker_hex"])
    assert len(marker) == 64
    assert marker[:32].rstrip(b"\0") == b"iOpenPod-Bootloader-v1"
    assert struct.unpack_from("<4I", marker, 32) == (1, 1, 33, 0x00130100)
    assert marker[48:].rstrip(b"\0") == b"1.0.0"


class Wire:
    def __init__(self, fail_block: bool = False) -> None:
        self.requests: list[UsbControlRequest] = []
        self.fail_block = fail_block
        self.handoff = False

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        self.requests.append(request)
        if request.request_type == 0x21 and request.request == 1:
            if self.fail_block and request.data_out:
                raise UsbControlError("transfer lost")
            if not request.data_out:
                assert self.handoff, "handoff must be journaled before the USB command"
                raise UsbControlError("writer took USB")
        if request.request_type == 0xA1 and request.request == 5:
            return UsbControlResponse(b"\x02", 1)
        if request.request_type == 0xA1 and request.request == 3:
            return UsbControlResponse(bytes((0, 0, 0, 0, 5, 0)), 6)
        return UsbControlResponse(
            bytes(request.data_in_length), request.transfer_length
        )

    def close(self) -> None:
        pass


def test_ambiguous_manifest_is_never_retried_and_intent_precedes_usb() -> None:
    wire = Wire()
    dfu = ClassicBootDfu(wire, Event())
    dfu.download(PLAN.image, lambda: setattr(wire, "handoff", True))
    downloads = [
        request
        for request in wire.requests
        if request.request_type == 0x21 and request.request == 1
    ]
    assert [request.value for request in downloads] == [0, 1, 2, 3]
    assert sum(not request.data_out for request in downloads) == 1


def test_failed_chunk_and_cancellation_never_launch_writer() -> None:
    wire = Wire(fail_block=True)
    with pytest.raises(UsbControlError):
        ClassicBootDfu(wire, Event()).download(
            PLAN.image, lambda: pytest.fail("launched")
        )
    assert len([request for request in wire.requests if request.request == 1]) == 1
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        ClassicBootDfu(Wire(), cancel).download(
            PLAN.image, lambda: pytest.fail("launched")
        )


class CryptoDfu(ClassicBootDfu):
    """Independent AES model tests CBC chaining and hardware-seal framing."""

    key = bytes(range(16))

    def probe(
        self, code: bytes, size: int, prefix: bytes = bytes(probes.PREFIX_SIZE)
    ) -> bytes:
        length = size - 16
        data, iv = prefix[16 : 16 + length], prefix[16 + length : 32 + length]
        cipher = _AES_CBC(self.key, AES.MODE_CBC, iv=iv)
        result = (
            cipher.encrypt(data)
            if length == 16 and code == probes.aes(length, encrypt=True)
            else cipher.decrypt(data)
        )
        return bytes(16) + result


@pytest.mark.parametrize("encrypted", [False, True])
def test_device_seal_and_authentication_for_both_apple_formats(encrypted: bool) -> None:
    dfu = CryptoDfu(Wire(), Event())
    body = bytes((index * 17) & 255 for index in range(0x1F800))
    sealed = bytearray(dfu.seal(body))
    if encrypted:
        sealed[7] = 1
        sealed[0x40:0x50] = _AES_CBC(dfu.key, AES.MODE_CBC, iv=bytes(16)).encrypt(
            hashlib.sha1(sealed[:64]).digest()[:16]
        )
        sealed[0x800:] = _AES_CBC(dfu.key, AES.MODE_CBC, iv=bytes(16)).encrypt(body)
    assert dfu.plaintext(bytes(sealed)) == body
    sealed[-1] ^= 1
    with pytest.raises(ValueError, match="body authentication"):
        dfu.plaintext(bytes(sealed))
