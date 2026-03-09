"""Shared infrastructure for bidirectional iTunesDB field definitions.

This module provides the :class:`FieldDef` dataclass, factory helpers,
transform / validator functions, exception hierarchy, and the read/write
helpers that all per-chunk ``*_defs.py`` modules build on.

Per-chunk field lists (``MHBD_FIELDS``, ``MHIT_FIELDS``, …) live in their
own ``*_defs.py`` modules.  The :data:`FIELD_REGISTRY` is assembled at
import time by :mod:`iTunesDB_Shared.__init__` from those modules.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Callable, Optional


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


class SectionLengthMismatchError(WriteError):
    """Written byte count does not match ``total_length``."""

    def __init__(self, section_type: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Section '{section_type}' length mismatch: "
            f"expected {expected}, got {actual}"
        )
        self.section_type = section_type
        self.expected = expected
        self.actual = actual


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. Transform & Validator Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Mac HFS+ epoch offset (seconds between 1904-01-01 and 1970-01-01).
MAC_EPOCH_OFFSET: int = 2082844800


def mac_to_unix(mac_ts: int) -> int:
    """Convert Mac HFS+ timestamp to Unix epoch."""
    return mac_ts - MAC_EPOCH_OFFSET if mac_ts > 0 else 0


def unix_to_mac(unix_ts: int) -> int:
    """Convert Unix epoch timestamp to Mac HFS+ timestamp."""
    return unix_ts + MAC_EPOCH_OFFSET if unix_ts > 0 else 0


def sample_rate_to_fixed(hz: int) -> int:
    """Encode sample rate as 16.16 fixed-point for MHIT offset 0x3C."""
    return (hz << 16) & 0xFFFFFFFF


def fixed_to_sample_rate(raw: int) -> int:
    """Decode 16.16 fixed-point sample rate to integer Hz."""
    return raw >> 16


def validate_rating(value: int) -> None:
    """Raise if rating is outside 0-100."""
    if not (0 <= value <= 100):
        raise ValueError(f"rating {value} outside 0-100")


def clamp_rating(value: int) -> int:
    """Clamp rating to 0-100."""
    return max(0, min(100, value))


def validate_volume(value: int) -> None:
    """Raise if volume adjustment is outside -255..+255."""
    if not (-255 <= value <= 255):
        raise ValueError(f"volume {value} outside -255..+255")


def encode_soundcheck(db: float) -> int:
    """Convert dB gain adjustment to Apple SoundCheck value.

    SoundCheck is a linear multiplier × 1000.  Loud tracks get small
    values (attenuation), quiet tracks get large values (boost).
    ``0`` means no adjustment (treated as 1000 = unity gain by iPod).
    """
    if db == 0.0:
        return 0
    return max(0, int(round(1000.0 * (10.0 ** (-db / 10.0)))))


def decode_soundcheck(raw: int) -> float:
    """Convert Apple SoundCheck value to dB gain adjustment."""
    import math
    if raw == 0:
        return 0.0
    return -10.0 * math.log10(raw / 1000.0)


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
    read_transform: Optional[Callable[..., Any]] = None
    write_transform: Optional[Callable[..., Any]] = None
    default: Any = 0
    validator: Optional[Callable[..., None]] = None
    min_header_length: Optional[int] = None
    required: bool = False
    section_type: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3b. List-container header sizes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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


def _i16(name: str, offset: int, **kw: Any) -> FieldDef:
    return FieldDef(name=name, offset=offset, size=2, struct_format="<h", **kw)


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

# Quick name→FieldDef lookup per section — rebuilt when registry is filled.
_FIELD_INDEX: dict[str, dict[str, FieldDef]] = {}


def _rebuild_index() -> None:
    """Rebuild the per-section name→FieldDef index from FIELD_REGISTRY."""
    _FIELD_INDEX.clear()
    for section, fields in FIELD_REGISTRY.items():
        _FIELD_INDEX[section] = {f.name: f for f in fields}


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


def get_field(section_type: str, field_name: str) -> FieldDef | None:
    """Look up a single field by section and name."""
    return _FIELD_INDEX.get(section_type, {}).get(field_name)


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
    struct.pack_into(field.struct_format, buffer, base_offset + field.offset, value)


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
    buffer[offset:offset + 4] = tag
    struct.pack_into("<I", buffer, offset + 4, header_length)
    struct.pack_into("<I", buffer, offset + 8, total_length_or_count)
