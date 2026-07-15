"""Shared infrastructure for bidirectional iTunesDB field definitions.

This module provides the :class:`FieldDef` dataclass, factory helpers,
transform / validator functions, exception hierarchy, and the read/write
helpers that all per-chunk ``*_defs.py`` modules build on.

Per-chunk field lists (``MHBD_FIELDS``, ``MHIT_FIELDS``, …) live in their
own ``*_defs.py`` modules.  The :data:`FIELD_REGISTRY` is assembled at
import time by :mod:`iopenpod.itunesdb_shared.__init__` from those modules.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Exception Hierarchy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class WriteError(Exception):
    """Base exception for iTunesDB write-time errors."""


class MissingRequiredFieldError(WriteError):
    """A field marked ``required=True`` was absent from the values dict."""

    def __init__(self, section_type: str, field_name: str) -> None:
        super().__init__(
            f"Required field '{field_name}' missing for section '{section_type}'"
        )
        self.section_type = section_type
        self.field_name = field_name


class InvalidFieldValueError(WriteError):
    """A field validator rejected the value."""

    def __init__(self, section_type: str, field_name: str, detail: str) -> None:
        super().__init__(
            f"Invalid value for '{field_name}' in section '{section_type}': {detail}"
        )
        self.section_type = section_type
        self.field_name = field_name


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. Transform & Validator Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Mac HFS+ epoch offset (seconds between 1904-01-01 and 1970-01-01).
MAC_EPOCH_OFFSET: int = 2082844800
_U32_MAX: int = 0xFFFFFFFF


def _int_or_default(value: Any, default: int = 0) -> int:
    """Coerce loose metadata to int without letting NaN/None leak through."""
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def mac_to_unix(mac_ts: int) -> int:
    """Convert Mac HFS+ timestamp to Unix epoch."""
    return mac_ts - MAC_EPOCH_OFFSET if mac_ts > 0 else 0


def unix_to_mac(unix_ts: int) -> int:
    """Convert Unix epoch timestamp to Mac HFS+ timestamp."""
    unix_ts = _int_or_default(unix_ts)
    if unix_ts <= 0:
        return 0
    # The on-disk field is u32 seconds from the 1904 Mac epoch.
    return min(unix_ts, _U32_MAX - MAC_EPOCH_OFFSET) + MAC_EPOCH_OFFSET


def sample_rate_to_fixed(hz: int) -> int:
    """Encode sample rate as 16.16 fixed-point for MHIT offset 0x3C."""
    hz = max(0, min(_int_or_default(hz), 0xFFFF))
    return hz << 16


def fixed_to_sample_rate(raw: int) -> int:
    """Decode 16.16 fixed-point sample rate to integer Hz."""
    return raw >> 16


def validate_rating(value: int) -> None:
    """Raise if rating is outside 0-100."""
    value = _int_or_default(value, -1)
    if not (0 <= value <= 100):
        raise ValueError(f"rating {value} outside 0-100")


def clamp_rating(value: int) -> int:
    """Clamp rating to 0-100."""
    value = _int_or_default(value)
    return max(0, min(100, value))


def validate_volume(value: int) -> None:
    """Raise if volume adjustment is outside -255..+255."""
    value = _int_or_default(value, -1000)
    if not (-255 <= value <= 255):
        raise ValueError(f"volume {value} outside -255..+255")


def filetype_to_string(val: int) -> str:
    """Convert a u32 filetype code to its ASCII representation.

    e.g. 0x4D503320 → "MP3", 0x4D344120 → "M4A"
    """
    if not isinstance(val, int) or val <= 0:
        return ""
    try:
        return val.to_bytes(4, "big").decode("ascii").rstrip("\x00").strip()
    except (OverflowError, UnicodeDecodeError):
        return str(val)


def strip_article(name: str) -> str:
    """Strip leading English articles (A, An, The) for sort field generation.

    iTunes auto-generates sort_title/sort_album/etc. by stripping common
    English leading articles.  Used by both the binary iTunesDB writer
    (MHOD type 52 jump tables) and the SQLite writer (sort key columns).
    """
    if not name:
        return name
    lower = name.lower()
    for article in ('the ', 'a ', 'an '):
        if lower.startswith(article):
            return name[len(article):]
    return name


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. FieldDef Dataclass
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass(frozen=True, slots=True)
class FieldDef:
    """Complete, bidirectional contract for one binary field.

    Attributes:
        name: Canonical snake_case identifier shared by parser and writer.
        offset: Byte offset within the section header (relative to chunk start).
        size: Byte width of the field.
        struct_format: :mod:`struct` format string (e.g. ``'<I'``, ``'B'``, ``'<8s'``).
        read_transform: Callable applied AFTER unpacking on parse.
        write_transform: Callable applied BEFORE packing on write.
        default: Value used when the field is absent from the data dict.
        validator: Callable that raises :class:`ValueError` if the value is invalid.
        min_header_length: Minimum ``header_length`` for this field to exist.
            ``None`` means the field is always present.
        required: If ``True``, :func:`write_fields` raises
            :class:`MissingRequiredFieldError` when the field is absent.
        section_type: ASCII tag of the parent section (e.g. ``'mhit'``).
    """

    name: str
    offset: int
    size: int
    struct_format: str
    read_transform: Callable[..., Any] | None = None
    write_transform: Callable[..., Any] | None = None
    default: Any = 0
    validator: Callable[..., None] | None = None
    min_header_length: int | None = None
    required: bool = False
    section_type: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3b. List-container header sizes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The generic header shared by every iTunesDB chunk:
#   +0x00  chunk_type  (4 bytes ASCII)
#   +0x04  header_len  (u32 LE)
#   +0x08  length_or_child_count  (u32 LE)
GENERIC_HEADER_STRUCT = struct.Struct("<4sII")
GENERIC_HEADER_SIZE: int = GENERIC_HEADER_STRUCT.size

# Simple list chunks (mhlt, mhla, mhli, mhlp) have only the 12-byte
# generic header padded to 92 bytes.  They don't carry FieldDef lists.

MHLT_HEADER_SIZE: int = 92
MHLA_HEADER_SIZE: int = 92
MHLI_HEADER_SIZE: int = 92
MHLP_HEADER_SIZE: int = 92


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Factory Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _u32(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=4, struct_format="<I", **kw)


def _i32(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=4, struct_format="<i", **kw)


def _u16(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=2, struct_format="<H", **kw)


def _u64(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=8, struct_format="<Q", **kw)


def _u8(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=1, struct_format="B", **kw)


def _f32(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=4, struct_format="<f", **kw)


def _raw(name: str, offset: int, size: int, **kw: Any) -> FieldDef:
    kw.setdefault("default", b"\x00" * size)
    return FieldDef(name=name, offset=offset, size=size,
                    struct_format=f"<{size}s", **kw)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. FIELD_REGISTRY & lookup helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Populated by __init__.py after all *_defs modules have been imported.
FIELD_REGISTRY: dict[str, list[FieldDef]] = {}


def get_fields(
    section_type: str,
    header_length: int | None = None,
) -> list[FieldDef]:
    """Return field definitions for *section_type*, optionally filtered.

    Args:
        section_type: ASCII chunk tag (e.g. ``'mhit'``, ``'mhbd'``).
        header_length: If provided, fields whose ``min_header_length``
            exceeds this value are excluded.

    Returns:
        List of :class:`FieldDef` in offset order.
    """
    fields = FIELD_REGISTRY.get(section_type, [])
    if header_length is not None:
        return [
            f for f in fields
            if f.min_header_length is None or header_length >= f.min_header_length
        ]
    return list(fields)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Read / Write Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def read_field(
    data: bytes | bytearray,
    base_offset: int,
    field: FieldDef,
    header_length: int | None = None,
) -> Any:
    """Read a single field from *data* at *base_offset*.

    Args:
        data: Raw byte buffer.
        base_offset: Start of the chunk in *data*.
        field: Field definition.
        header_length: Chunk header length (for version guard).

    Returns:
        The unpacked (and optionally transformed) value, or
        ``field.default`` if the header is too small.
    """
    if field.min_header_length is not None:
        if header_length is None or header_length < field.min_header_length:
            return field.default
    abs_offset = base_offset + field.offset
    raw = struct.unpack_from(field.struct_format, data, abs_offset)[0]
    if field.read_transform is not None:
        return field.read_transform(raw)
    return raw


def read_fields(
    data: bytes | bytearray,
    base_offset: int,
    section_type: str,
    header_length: int | None = None,
) -> dict[str, Any]:
    """Read all fields for *section_type* into a dict.

    This is the read-side counterpart to :func:`write_fields`.

    Args:
        data: Raw byte buffer.
        base_offset: Start of the chunk in *data*.
        section_type: Chunk tag (e.g. ``'mhit'``).
        header_length: Actual header length from the chunk.  Extended
            fields not covered by this length are set to their defaults.

    Returns:
        Dict mapping field name → value.
    """
    result: dict[str, Any] = {}
    for field in FIELD_REGISTRY.get(section_type, []):
        result[field.name] = read_field(data, base_offset, field, header_length)
    return result


def write_field(
    buffer: bytearray,
    base_offset: int,
    field: FieldDef,
    value: Any,
    section_type: str = "",
) -> None:
    """Pack a single field value into *buffer*.

    Applies ``write_transform`` then ``validator`` before packing.

    Args:
        buffer: Mutable byte buffer to write into.
        base_offset: Start of the chunk header in *buffer*.
        field: Field definition.
        value: The logical value to write.
        section_type: For error messages only.
    """
    if field.write_transform is not None:
        value = field.write_transform(value)
    if field.validator is not None:
        try:
            field.validator(value)
        except (ValueError, TypeError) as exc:
            raise InvalidFieldValueError(
                section_type or field.section_type, field.name, str(exc),
            ) from exc
    # Coerce to the type required by the format code so that floats or other
    # numeric types from metadata sources never reach struct.pack_into as the
    # wrong type (e.g. float for an integer field, or int for a float field).
    format_code = field.struct_format[-1]
    if format_code in 'IiHhQqBbNnP':
        if not isinstance(value, int):
            value = int(value)
        # Clamp to the valid range for the format so bad metadata (e.g. negative
        # BPM, oversized play counts) never crashes the packer.
        int_ranges = {
            'B': (0, 0xFF),
            'H': (0, 0xFFFF),
            'I': (0, 0xFFFF_FFFF),
            'Q': (0, 0xFFFF_FFFF_FFFF_FFFF),
            'b': (-0x80, 0x7F),
            'h': (-0x8000, 0x7FFF),
            'i': (-0x8000_0000, 0x7FFF_FFFF),
            'q': (-0x8000_0000_0000_0000, 0x7FFF_FFFF_FFFF_FFFF),
        }
        if format_code in int_ranges:
            lower, upper = int_ranges[format_code]
            value = max(lower, min(upper, value))
    elif format_code in 'fd':
        if not isinstance(value, float):
            value = float(value)
    try:
        struct.pack_into(field.struct_format, buffer, base_offset + field.offset, value)
    except struct.error as exc:
        raise struct.error(
            f"Failed to pack field '{field.name}' (format={field.struct_format!r}, "
            f"value={value!r} type={type(value).__name__}): {exc}"
        ) from exc


def write_fields(
    buffer: bytearray,
    base_offset: int,
    section_type: str,
    values: dict[str, Any],
    header_length: int,
) -> None:
    """Write all applicable fields from *values* into *buffer*.

    This is the single serialization entrypoint used by the writer.
    Fields are written in offset order.  Fields whose
    ``min_header_length`` exceeds *header_length* are skipped.

    Args:
        buffer: Pre-allocated mutable buffer (must be ≥ header_length).
        base_offset: Chunk start position in *buffer*.
        section_type: Chunk tag (e.g. ``'mhit'``).
        values: Field name → logical value mapping.
        header_length: Target header size.  Fields beyond this are skipped.

    Raises:
        MissingRequiredFieldError: A ``required`` field is missing from *values*.
        InvalidFieldValueError: A validator rejected a value.
    """
    for field in FIELD_REGISTRY.get(section_type, []):
        # Skip fields outside the target header.
        if field.min_header_length is not None and header_length < field.min_header_length:
            continue

        if field.name in values:
            value = values[field.name]
        elif field.required:
            raise MissingRequiredFieldError(section_type, field.name)
        else:
            value = field.default

        write_field(buffer, base_offset, field, value, section_type)


def write_generic_header(
    buffer: bytearray,
    offset: int,
    tag: bytes,
    header_length: int,
    total_length_or_count: int,
) -> None:
    """Write the 12-byte generic iTunesDB chunk header.

    Args:
        buffer: Target buffer.
        offset: Position in buffer.
        tag: 4-byte ASCII tag (e.g. ``b'mhit'``).
        header_length: Header size to write at +0x04.
        total_length_or_count: Value for +0x08 (total_length for item
            chunks, child_count for list chunks).
    """
    GENERIC_HEADER_STRUCT.pack_into(
        buffer,
        offset,
        tag,
        header_length,
        total_length_or_count,
    )


def write_list_header(tag: bytes, header_length: int, child_count: int) -> bytes:
    """Build a padded list-container header.

    Simple list chunks such as ``mhlt``, ``mhla``, ``mhli``, and ``mhlp``
    store their child count in the generic header's third field and keep
    the rest of their 92-byte header zero-filled.
    """
    header = bytearray(header_length)
    write_generic_header(header, 0, tag, header_length, child_count)
    return bytes(header)


def write_list_chunk(
    tag: bytes,
    header_length: int,
    child_chunks: Iterable[bytes],
) -> bytes:
    """Build a simple list-container chunk from its child chunks."""
    chunks = tuple(child_chunks)
    return write_list_header(tag, header_length, len(chunks)) + b"".join(chunks)
