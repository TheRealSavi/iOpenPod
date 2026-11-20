"""Pure composition of the common Classic 2.0.5 image; no device operations."""

from __future__ import annotations

import hashlib
import struct
import zlib

from .classic_layout import EXPANDED_LAYOUT, MAX_OS_BODY_BYTES, STOCK_LAYOUT

APPLE_VERSION = "2.0.5"
IMAGE_TARGET = 0x43534C43  # ASCII CLSC, independent of updater family IDs.
IMAGE_SCHEMA = 2
HEADER_BYTES = 0x800
MAX_BODY_BYTES = MAX_OS_BODY_BYTES
FIRMWARE_BYTES = EXPANDED_LAYOUT.end
FIRMWARE_SHA256 = "9450c5b51f8785d41c1eef041eac3c7a521d0b325d730f591759b49d041086aa"
OSOS_OFFSET = EXPANDED_LAYOUT.osos
AUPD_OFFSET = EXPANDED_LAYOUT.aupd
OSOS_LENGTH_OFFSET = 0x5038
AUPD_STATUS_OFFSET = 0x5058
MARKER = b"IOPOD.UNSIGNED2\0"


def wrap_shared_os(body: bytes) -> bytes:
    if not 1 <= len(body) <= MAX_BODY_BYTES:
        raise ValueError("OS body exceeds the common Classic image bound")
    body += bytes(-len(body) % 16)
    header = bytearray(HEADER_BYTES)
    header[:8] = b"87021.0\x7f"
    struct.pack_into(
        "<6I",
        header,
        8,
        0,
        len(body),
        zlib.crc32(body),
        HEADER_BYTES,
        IMAGE_TARGET,
        IMAGE_SCHEMA,
    )
    header[32:48] = MARKER
    struct.pack_into("<I", header, 64, zlib.crc32(header[:64]))
    return bytes(header) + body


def validate_shared_os(image: bytes) -> None:
    if not HEADER_BYTES + 16 <= len(image) <= HEADER_BYTES + MAX_BODY_BYTES:
        raise ValueError("Invalid common Classic OS image size")
    entry, size, crc, header, target, schema = struct.unpack_from("<6I", image, 8)
    if (
        image[:8] != b"87021.0\x7f"
        or entry
        or size % 16
        or size != len(image) - HEADER_BYTES
        or (header, target, schema) != (HEADER_BYTES, IMAGE_TARGET, IMAGE_SCHEMA)
        or image[32:48] != MARKER
        or any(image[48:64])
        or any(image[68:HEADER_BYTES])
        or struct.unpack_from("<I", image, 64)[0] != zlib.crc32(image[:64])
        or crc != zlib.crc32(image[HEADER_BYTES:])
    ):
        raise ValueError("Invalid common Classic OS framing or checksum")


def compose_shared_firmware(stock: bytes, osos: bytes) -> bytes:
    """Expand the OS slot and relocate the intact AUPD/hash tail.

    Apple's normal-update finalizer preserves each iPod's hash record separately.
    No device identity or hardware authentication is embedded in this artifact.
    """
    if (
        len(stock) != STOCK_LAYOUT.end
        or hashlib.sha256(stock).hexdigest() != FIRMWARE_SHA256
    ):
        raise ValueError("Expected the pinned original Apple 2.0.5 firmware member")
    validate_shared_os(osos)
    if len(osos) > EXPANDED_LAYOUT.os_slot_bytes:
        raise ValueError("Common OS exceeds its allocated firmware slot")
    if (
        STOCK_LAYOUT.osos != EXPANDED_LAYOUT.osos
        or EXPANDED_LAYOUT.hash_record - EXPANDED_LAYOUT.aupd
        != STOCK_LAYOUT.hash_record - STOCK_LAYOUT.aupd
        or EXPANDED_LAYOUT.end - EXPANDED_LAYOUT.aupd
        != STOCK_LAYOUT.end - STOCK_LAYOUT.aupd
        or struct.unpack_from("<I", stock, 0x505C)[0] != STOCK_LAYOUT.aupd
        or struct.unpack_from("<I", stock, 0x5084)[0] != STOCK_LAYOUT.hash_record
    ):
        raise ValueError("Unexpected original Classic directory or tail layout")
    result = bytearray(stock[: STOCK_LAYOUT.osos])
    result += osos + bytes(EXPANDED_LAYOUT.os_slot_bytes - len(osos))
    result += stock[STOCK_LAYOUT.aupd :]
    struct.pack_into("<I", result, OSOS_LENGTH_OFFSET, len(osos))
    struct.pack_into("<I", result, 0x505C, EXPANDED_LAYOUT.aupd)
    struct.pack_into("<I", result, 0x5084, EXPANDED_LAYOUT.hash_record)
    # Bds must never run Apple's bundled NOR updater over the custom loader.
    struct.pack_into("<I", result, AUPD_STATUS_OFFSET, 1)
    return bytes(result)


def require_firmware_capacity(
    partition_bytes: int, *, image_bytes: int = FIRMWARE_BYTES
) -> None:
    """Capacity is a live observation, never inferred from retail model size."""
    if (
        type(partition_bytes) is not int
        or type(image_bytes) is not int
        or not 0 < image_bytes <= FIRMWARE_BYTES
        or not image_bytes <= partition_bytes <= 256 * 1024 * 1024
    ):
        raise ValueError("The observed firmware partition cannot hold the shared image")
