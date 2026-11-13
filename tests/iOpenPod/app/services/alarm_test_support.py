"""Shared virtual-device setup for Alarm application workflows."""

import struct
from pathlib import Path

from storage import Storage
from storage.testing import VirtualStoragePlatform


def write_classic_language(root: Path, language: int = 0) -> None:
    path = root / "iPod_Control/Device/Preferences"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bytearray(2956)
    struct.pack_into("<I", data, 0, 0x3D)
    struct.pack_into("<I", data, 0xAF8, language)
    path.write_bytes(data)


def virtual_storage(root: Path) -> Storage:
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    return Storage(platform)
