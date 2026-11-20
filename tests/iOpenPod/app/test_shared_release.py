"""Cold-cache offline preparation, cache repair and strict bundled-image framing."""

import hashlib
import socket
import struct
import zlib
from pathlib import Path
from threading import Event

import pytest

from iOpenPod.app.firmware import shared_release
from iOpenPod.app.firmware.classic_layout import EXPANDED_LAYOUT, STOCK_LAYOUT
from iOpenPod.app.firmware.classic_shared import (
    FIRMWARE_BYTES,
    OSOS_LENGTH_OFFSET,
    OSOS_OFFSET,
    validate_shared_os,
)
from storage import AtomicHostFile


def no_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("Firmware preparation must never access the network")


def test_complete_release_prepares_offline_without_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    release = shared_release.SharedFirmwareRelease(tmp_path)
    image = release.prepare(Event(), lambda _: None)
    assert len(image) == FIRMWARE_BYTES
    assert hashlib.sha256(image).hexdigest() == shared_release.IMAGE_SHA256
    osos_size = struct.unpack_from("<I", image, OSOS_LENGTH_OFFSET)[0]
    osos = image[OSOS_OFFSET : OSOS_OFFSET + osos_size]
    validate_shared_os(osos)
    assert EXPANDED_LAYOUT.os_slot_bytes == 16 * 1024 * 1024
    assert struct.unpack_from("<I", image, 0x505C)[0] == EXPANDED_LAYOUT.aupd
    assert struct.unpack_from("<I", image, 0x5084)[0] == EXPANDED_LAYOUT.hash_record
    assert struct.unpack_from("<I", image, 0x5058)[0] == 1
    assert shared_release.STOCK.payload_bytes == STOCK_LAYOUT.end
    assert len(image) > shared_release.STOCK.payload_bytes
    # Distribution regression: the complete OS must include the manifest mod,
    # not merely advertise a newer platform version in Host metadata.
    at = 0xB798 + 0x0F9414
    assert osos[at : at + 4] == bytes.fromhex("0030a0e3")
    assert shared_release.MOD_VERSION.encode() + b"\0" in osos
    for label in (
        b"Mod Version String",
        b"Mod Version in About",
        b"Unsigned Game Manifests",
        b"Mod Menu",
        b"Expanded Mod Memory",
        b"Light / Dark Appearance",
        b"Now Playing Preview Artwork",
        b"Bootloader Report",
        b"iOpenPodBootReport",
        b"Appearance",
        b"iOpenPod_Appearance_Toggle",
        b"Mods",
    ):
        assert label + b"\0" in osos
    assert b"iOpenPod_Mods_Screen\0" in osos
    assert b"iOpenPod_Mods_Layout\0" in osos
    assert b"iPod_Control\\Device\\iOPAppearance\0" in osos
    assert (
        tmp_path / "shared" / shared_release.MOD_VERSION / "firmware.bin"
    ).read_bytes() == image
    assert not list(tmp_path.glob("*.ipsw"))
    assert release.prepare(Event(), lambda _: None) == image


@pytest.fixture
def asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes]:
    image = b"reviewed universal firmware" * 64
    monkeypatch.setattr(shared_release, "FIRMWARE_BYTES", len(image))
    monkeypatch.setattr(
        shared_release, "IMAGE_SHA256", hashlib.sha256(image).hexdigest()
    )
    path = tmp_path / "package/assets/firmware/classic-shared/firmware.zlib"
    path.parent.mkdir(parents=True)
    path.write_bytes(zlib.compress(image))

    def resource_files(_package: str) -> Path:
        return tmp_path / "package"

    monkeypatch.setattr(shared_release, "files", resource_files)
    return path, image


def test_valid_cache_is_reused_without_unpacking(
    tmp_path: Path, asset: tuple[Path, bytes]
) -> None:
    path, image = asset
    destination = tmp_path / "shared" / shared_release.MOD_VERSION / "firmware.bin"
    AtomicHostFile(destination).replace_bytes(image)
    path.unlink()
    assert (
        shared_release.SharedFirmwareRelease(tmp_path).prepare(Event(), lambda _: None)
        == image
    )


@pytest.mark.parametrize(
    "corruption",
    (
        "truncated",
        "trailing",
        "expanded",
        "mismatch",
        "invalid",
        "compressed-oversize",
        "missing",
    ),
)
def test_damaged_bundle_never_publishes_or_downloads(
    tmp_path: Path,
    asset: tuple[Path, bytes],
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    path, image = asset
    variants = {
        "truncated": zlib.compress(image)[:20],
        "trailing": zlib.compress(image) + b"unexpected",
        "expanded": zlib.compress(bytes(len(image) + 1)),
        "mismatch": zlib.compress(bytes(len(image))),
        "invalid": b"not zlib",
        "compressed-oversize": bytes(len(image) + 1),
    }
    if corruption == "missing":
        path.unlink()
    else:
        path.write_bytes(variants[corruption])
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    with pytest.raises((ValueError, FileNotFoundError)):
        shared_release.SharedFirmwareRelease(tmp_path).prepare(Event(), lambda _: None)
    assert not (
        tmp_path / "shared" / shared_release.MOD_VERSION / "firmware.bin"
    ).exists()


@pytest.mark.parametrize("size_change", (-1, 0, 1))
def test_corrupted_cache_is_rebuilt_from_bundle(
    tmp_path: Path, asset: tuple[Path, bytes], size_change: int
) -> None:
    _, image = asset
    destination = tmp_path / "shared" / shared_release.MOD_VERSION / "firmware.bin"
    AtomicHostFile(destination).replace_bytes(bytes(len(image) + size_change))
    assert (
        shared_release.SharedFirmwareRelease(tmp_path).prepare(Event(), lambda _: None)
        == image
    )
    assert destination.read_bytes() == image


@pytest.mark.parametrize("before", (True, False))
def test_cancellation_never_publishes_partial_preparation(
    tmp_path: Path, asset: tuple[Path, bytes], before: bool
) -> None:
    cancel = Event()
    if before:
        cancel.set()
    with pytest.raises(InterruptedError):
        shared_release.SharedFirmwareRelease(tmp_path).prepare(
            cancel, lambda _: cancel.set()
        )
    assert not (
        tmp_path / "shared" / shared_release.MOD_VERSION / "firmware.bin"
    ).exists()
