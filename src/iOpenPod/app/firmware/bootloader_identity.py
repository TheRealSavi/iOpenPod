"""Decode an iOpenPod marker from a plaintext, device-read Classic loader body.

The marker identifies a build; it does not by itself authorize an OS upload.
Compatibility still requires the qualified complete executable digest.
"""

import re
import struct
from dataclasses import dataclass

from .bootloader_targets import CLASSIC_BOOTLOADERS

IDENTIFIER = "iOpenPod-Bootloader-v1"
_MAGIC = (IDENTIFIER.encode() + b"\0").ljust(32, b"\0")
MARKER_OFFSETS = tuple(
    sorted({109952, *(t.gap_start - 64 for t in CLASSIC_BOOTLOADERS)})
)


@dataclass(frozen=True)
class BootloaderIdentity:
    schema: int
    abi: int
    target: int
    hardware: int
    version: str


def decode_bootloader_marker(raw: bytes) -> BootloaderIdentity | None:
    """Decode one bounded PAD record, without treating it as code verification."""
    if len(raw) != 64:
        raise ValueError("Incomplete iOpenPod bootloader marker")
    if not raw.startswith(IDENTIFIER.encode()):
        return None
    version, separator, padding = raw[48:].partition(b"\0")
    if (
        raw[:32] != _MAGIC
        or not separator
        or any(padding)
        or re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?", version) is None
    ):
        raise ValueError("Damaged iOpenPod bootloader marker")
    schema, abi, target, hardware = struct.unpack_from("<4I", raw, 32)
    return BootloaderIdentity(schema, abi, target, hardware, version.decode("ascii"))


def read_bootloader_identity(body: bytes) -> BootloaderIdentity | None:
    """Read only established PAD slots, rejecting ambiguous or damaged markers."""
    if len(body) != 0x1F800:
        raise ValueError("Incomplete Classic bootloader body")
    found = [
        marker
        for offset in MARKER_OFFSETS
        if (marker := decode_bootloader_marker(body[offset : offset + 64])) is not None
    ]
    if len(found) > 1:
        raise ValueError("Ambiguous iOpenPod bootloader markers")
    return found[0] if found else None
