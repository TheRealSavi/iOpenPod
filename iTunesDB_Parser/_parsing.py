"""
Internal parsing helpers shared across iTunesDB chunk parsers.

Provides:
- Pre-compiled ``struct.Struct`` objects for common binary field widths.
- :func:`parse_children` — iterates child chunks and collects results.
- :func:`parse_child_list` — one-call helper for pure-list containers
  (mhlt, mhla, mhli, mhlp) that contain only homogeneous children.

These helpers eliminate duplicated child-iteration boilerplate across
the dozen+ chunk parser modules.
"""

from __future__ import annotations

import struct
from typing import Any

from .exceptions import CorruptHeaderError, InsufficientDataError

# ── Pre-compiled struct objects ──────────────────────────────────────
# Used by callers (e.g. mhod_parser) that do inline struct reads.
# The Shared defs module still uses ad-hoc struct.unpack calls; these
# are for Parser-local code.

UINT16_LE = struct.Struct("<H")
UINT32_LE = struct.Struct("<I")
UINT64_LE = struct.Struct("<Q")
INT32_LE = struct.Struct("<i")
FLOAT32_LE = struct.Struct("<f")

# The generic chunk header shared by every iTunesDB chunk:
#   +0x00  chunk_type  (4 bytes ASCII)
#   +0x04  header_len  (u32 LE)
#   +0x08  length_or_child_count  (u32 LE)
_GENERIC_HEADER = struct.Struct("<4sII")
GENERIC_HEADER_SIZE = _GENERIC_HEADER.size  # 12 bytes


def read_generic_header(
    data: bytes | bytearray,
    offset: int,
) -> tuple[str, int, int]:
    """Read the 12-byte generic chunk header at *offset*.

    Returns:
        Tuple of ``(chunk_type, header_length, length_or_child_count)``.

    Raises:
        InsufficientDataError: If fewer than 12 bytes remain at *offset*.
        CorruptHeaderError: If the chunk type bytes are not valid ASCII.
    """
    end = offset + GENERIC_HEADER_SIZE
    if end > len(data):
        raise InsufficientDataError(offset, GENERIC_HEADER_SIZE, len(data) - offset)

    raw_type, header_length, length_or_children = _GENERIC_HEADER.unpack_from(data, offset)

    try:
        chunk_type = raw_type.decode("ascii")
    except UnicodeDecodeError:
        raise CorruptHeaderError(
            offset,
            f"chunk type bytes are not valid ASCII: {raw_type!r}",
        )

    return chunk_type, header_length, length_or_children


# ── Child-iteration helpers ──────────────────────────────────────────

ParseResult = dict[str, Any]
"""Return type of every chunk parser: ``{"next_offset": int, "data": ...}``."""


def parse_children(
    data: bytes | bytearray,
    offset: int,
    child_count: int,
) -> tuple[list[dict[str, Any]], int]:
    """Parse *child_count* consecutive child chunks starting at *offset*.

    Args:
        data: Full database byte buffer.
        offset: Byte position of the first child chunk.
        child_count: Number of children to parse.

    Returns:
        Tuple of ``(children_list, next_offset)`` where each child is
        ``{"chunk_type": str, "data": <parsed>}``.
    """
    # Lazy import to avoid circular dependency (chunk_parser imports us).
    from .chunk_parser import parse_chunk

    children: list[dict[str, Any]] = []
    current = offset
    for _ in range(child_count):
        parsed, chunk_type = parse_chunk(data, current)
        current = parsed["next_offset"]
        children.append({"chunk_type": chunk_type, "data": parsed["data"]})
    return children, current


def parse_child_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse a pure-list container (mhlt, mhla, mhli, mhlp).

    These chunks consist solely of a thin header followed by *child_count*
    sub-chunks with no additional header fields.

    Returns:
        ``{"next_offset": int, "data": list[...]}``
    """
    children, next_offset = parse_children(data, offset + header_length, child_count)
    return {"next_offset": next_offset, "data": children}
