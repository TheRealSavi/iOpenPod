"""MHOD string and type helpers for ArtworkDB."""

from __future__ import annotations

import struct

from .binary import read_u32
from .constants import MHOD_HEADER_SIZE, MHOD_TYPE_MAP, ArtworkMhodType


def mhod_type_info(mhod_type: int) -> dict[str, str] | None:
    try:
        return MHOD_TYPE_MAP.get(ArtworkMhodType(mhod_type))
    except ValueError:
        return None


def is_mhod_container(mhod_type: int) -> bool:
    info = mhod_type_info(mhod_type)
    return bool(info and info["type"] == "Container")


def mhod_type_name(mhod_type: int) -> str | None:
    info = mhod_type_info(mhod_type)
    return info["name"] if info else None


def mhod_string_encoding(mhod_type: int) -> tuple[str, int]:
    if mhod_type == ArtworkMhodType.FILE_NAME:
        return "utf-16-le", 2
    return "utf-8", 1


def encode_mhod_string_body(mhod_type: int, value: str) -> bytes:
    encoding, encoding_byte = mhod_string_encoding(mhod_type)
    encoded = value.encode(encoding)
    padding = (4 - (len(encoded) % 4)) % 4

    body = struct.pack("<I", len(encoded))
    body += struct.pack("<B", encoding_byte)
    body += b"\x00" * 3
    body += b"\x00" * 4
    body += encoded
    body += b"\x00" * padding
    return body


def decode_mhod_string_body(data: bytes | bytearray, body_offset: int, body_end: int) -> str | None:
    if body_offset + 12 > body_end:
        return None

    string_byte_length = read_u32(data, body_offset)
    encoding = data[body_offset + 4]
    raw_start = body_offset + 12
    raw_end = min(body_end, raw_start + string_byte_length)
    raw = bytes(data[raw_start:raw_end])
    try:
        if encoding == 2:
            return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        return raw.decode("utf-8", errors="replace").rstrip("\x00")
    except UnicodeError:
        return None


def decode_mhod_string_chunk(data: bytes | bytearray, offset: int, total_size: int) -> str | None:
    if offset + MHOD_HEADER_SIZE + 12 > offset + total_size:
        return None
    header_size = read_u32(data, offset + 4)
    if header_size < MHOD_HEADER_SIZE or header_size > total_size:
        return None
    return decode_mhod_string_body(data, offset + header_size, offset + total_size)

