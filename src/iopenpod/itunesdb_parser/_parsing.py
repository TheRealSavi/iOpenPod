"""
Internal parsing helpers shared across iTunesDB chunk parsers.

Provides:
- Pre-compiled ``struct.Struct`` objects for common binary field widths.
- :func:`read_generic_header` — reads the 12-byte generic chunk header.

Child-iteration helpers live in :mod:`chunk_parser` to avoid circular
imports (they need ``parse_chunk``, which dispatches back to the typed
parsers that use this module's struct helpers).
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from iopenpod.itunesdb_shared.field_base import GENERIC_HEADER_SIZE, GENERIC_HEADER_STRUCT

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

ParseResult = dict[str, Any]
"""Return type of every chunk parser: ``{"next_offset": int, "data": ...}``."""


_preserve_raw_chunks: ContextVar[bool] = ContextVar(
    "iopenpod_preserve_raw_itunesdb_chunks", default=False,
)


@contextmanager
def preserve_raw_chunks(enabled: bool) -> Iterator[None]:
    """Choose whether this parse records exact unmodelled chunk bytes."""
    token = _preserve_raw_chunks.set(enabled)
    try:
        yield
    finally:
        _preserve_raw_chunks.reset(token)


def raw_chunk_preservation_enabled() -> bool:
    """Whether the current parse should expose forensic raw chunk data."""
    return _preserve_raw_chunks.get()


def raw_chunk_metadata(
    data: bytes | bytearray,
    *,
    offset: int,
    header_length: int,
    declared_length_or_child_count: int,
    end_offset: int,
    parsed_body_end: int,
) -> dict[str, int | bytes]:
    """Return exact bytes not represented structurally by a parsed chunk.

    ``raw_header`` retains every header byte, including undefined fields and
    padding. ``unparsed_bytes`` is a leaf body or the trailer left after a
    container's declared children. Together with child records, these values
    cover every byte in the original chunk without duplicating child bodies.
    """
    buffer_end = len(data)
    actual_end = min(max(offset, end_offset), buffer_end)
    actual_header_end = min(max(offset, offset + header_length), actual_end)
    actual_body_end = min(max(actual_header_end, parsed_body_end), actual_end)
    return {
        "offset": offset,
        "header_length": header_length,
        "declared_length_or_child_count": declared_length_or_child_count,
        "end_offset": actual_end,
        "raw_header": bytes(data[offset:actual_header_end]),
        "unparsed_bytes": bytes(data[actual_body_end:actual_end]),
    }


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

    raw_type, header_length, length_or_children = GENERIC_HEADER_STRUCT.unpack_from(
        data,
        offset,
    )

    try:
        chunk_type = raw_type.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CorruptHeaderError(
            offset,
            f"chunk type bytes are not valid ASCII: {raw_type!r}",
        ) from exc

    return chunk_type, header_length, length_or_children
