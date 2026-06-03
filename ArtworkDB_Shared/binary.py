"""Small binary helpers for walking ArtworkDB chunks."""

from __future__ import annotations

import struct
from dataclasses import dataclass

GENERIC_CHUNK_HEADER_SIZE = 12
MIN_TYPED_CHUNK_HEADER_SIZE = 14


@dataclass(frozen=True)
class ChunkHeader:
    tag: str
    header_size: int
    length_or_count: int


def read_chunk_header(data: bytes | bytearray, offset: int) -> ChunkHeader:
    if offset < 0 or offset + GENERIC_CHUNK_HEADER_SIZE > len(data):
        raise ValueError(f"ArtworkDB chunk header outside buffer at offset {offset}")
    tag = bytes(data[offset:offset + 4]).decode("utf-8", errors="replace")
    header_size = struct.unpack_from("<I", data, offset + 4)[0]
    length_or_count = struct.unpack_from("<I", data, offset + 8)[0]
    return ChunkHeader(tag, header_size, length_or_count)


def chunk_fits(data: bytes | bytearray, offset: int, total_size: int, min_header_size: int = GENERIC_CHUNK_HEADER_SIZE) -> bool:
    return (
        offset >= 0
        and total_size >= min_header_size
        and offset + total_size <= len(data)
    )


def total_length_is_valid(
    data: bytes | bytearray,
    offset: int,
    header_size: int,
    total_size: int,
    min_header_size: int = GENERIC_CHUNK_HEADER_SIZE,
    end: int | None = None,
) -> bool:
    boundary = len(data) if end is None else min(len(data), end)
    return (
        offset >= 0
        and header_size >= min_header_size
        and total_size >= header_size
        and offset + total_size <= boundary
    )


def read_u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_i16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def read_u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u64(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]
