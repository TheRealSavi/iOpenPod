"""Utilities for navigating iTunesDB byte-walk JSON without loading it all.

The forensic export is deliberately verbose.  A real iTunesDB can therefore
produce a JSON file too large for ``json.load`` or a text editor to handle
comfortably.  This module builds a lightweight index from the on-disk JSON and
loads only the one selected chunk object on demand.
"""

from __future__ import annotations

import json
import mmap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CHUNK_MARKER = b'"chunk": "'


@dataclass(frozen=True, slots=True)
class ByteWalkChunkIndexEntry:
    """Enough information to find one complete chunk object in a JSON file."""

    json_offset: int
    chunk_type: str
    caption: str
    file_offset: int
    byte_length: int


def _json_string_at(data: mmap.mmap, quote_offset: int) -> tuple[str, int]:
    """Decode one JSON string beginning at *quote_offset* and return its end."""
    cursor = quote_offset + 1
    escaped = False
    while cursor < len(data):
        byte = data[cursor]
        if escaped:
            escaped = False
        elif byte == ord("\\"):
            escaped = True
        elif byte == ord('"'):
            raw = data[quote_offset:cursor + 1].decode("utf-8")
            return json.loads(raw), cursor + 1
        cursor += 1
    raise ValueError("unterminated JSON string in byte-walk document")


def _property_string(
    data: mmap.mmap,
    property_name: bytes,
    *,
    start: int,
    stop: int,
) -> str:
    """Read a nearby quoted property without parsing the full document."""
    property_offset = data.find(property_name, start, stop)
    if property_offset < 0:
        raise ValueError(f"byte-walk chunk is missing {property_name!r}")
    quote_offset = property_offset + len(property_name)
    return _json_string_at(data, quote_offset)[0]


def _property_int(
    data: mmap.mmap,
    property_name: bytes,
    *,
    start: int,
    stop: int,
) -> int:
    """Read a nearby non-negative integer property."""
    property_offset = data.find(property_name, start, stop)
    if property_offset < 0:
        raise ValueError(f"byte-walk chunk is missing {property_name!r}")
    cursor = property_offset + len(property_name)
    end = cursor
    while end < stop and data[end: end + 1].isdigit():
        end += 1
    if end == cursor:
        raise ValueError(f"byte-walk chunk has an invalid {property_name!r}")
    return int(data[cursor:end])


def index_byte_walk_json(path: str | Path) -> list[ByteWalkChunkIndexEntry]:
    """Build a low-memory searchable chunk index for a byte-walk JSON file.

    Only the fixed, leading fields of each chunk are read.  The potentially
    enormous nested ``bytes`` arrays remain on disk until a user selects a
    particular chunk in the inspector.
    """
    source = Path(path)
    entries: list[ByteWalkChunkIndexEntry] = []
    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        cursor = 0
        data_length = len(data)
        while True:
            marker = data.find(_CHUNK_MARKER, cursor)
            if marker < 0:
                break
            chunk_type, marker_end = _json_string_at(data, marker + len(_CHUNK_MARKER) - 1)
            metadata_end = min(data_length, marker + 16_384)
            caption = _property_string(
                data,
                b'"caption": ',
                start=marker_end,
                stop=metadata_end,
            )
            raw_file_offset = _property_string(
                data,
                b'"file_offset": ',
                start=marker_end,
                stop=metadata_end,
            )
            byte_length = _property_int(
                data,
                b'"byte_length": ',
                start=marker_end,
                stop=metadata_end,
            )
            object_offset = data.rfind(b"{", max(0, marker - 256), marker)
            if object_offset < 0:
                raise ValueError("could not find the start of a byte-walk chunk")
            entries.append(
                ByteWalkChunkIndexEntry(
                    json_offset=object_offset,
                    chunk_type=chunk_type,
                    caption=caption,
                    file_offset=int(raw_file_offset, 0),
                    byte_length=byte_length,
                ),
            )
            cursor = marker_end
    if not entries:
        raise ValueError("this file does not contain an iOpenPod byte-walk JSON document")
    return entries


def _object_end(data: mmap.mmap, object_offset: int) -> int:
    """Find a JSON object's closing brace without loading unrelated chunks."""
    depth = 0
    in_string = False
    escaped = False
    for cursor in range(object_offset, len(data)):
        byte = data[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue
        if byte == ord('"'):
            in_string = True
        elif byte == ord("{"):
            depth += 1
        elif byte == ord("}"):
            depth -= 1
            if depth == 0:
                return cursor + 1
    raise ValueError("unterminated JSON object in byte-walk document")


def load_indexed_chunk(
    path: str | Path,
    entry: ByteWalkChunkIndexEntry,
) -> dict[str, Any]:
    """Load exactly one indexed chunk object from an on-disk byte-walk JSON."""
    source = Path(path)
    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        end = _object_end(data, entry.json_offset)
        parsed = json.loads(data[entry.json_offset:end].decode("utf-8"))
    if not isinstance(parsed, dict) or parsed.get("chunk") != entry.chunk_type:
        raise ValueError("byte-walk index does not match the selected chunk")
    return parsed


def hex_interpretations(hex_text: str) -> dict[str, str]:
    """Return useful human-readable interpretations of hexadecimal input.

    Whitespace, ``0x`` prefixes, commas, and colons are accepted so copied
    hexdumps can be pasted into the inspector without cleanup.
    """
    normalized = (
        hex_text.lower()
        .replace("0x", "")
        .replace(" ", "")
        .replace("\n", "")
        .replace("\t", "")
        .replace(":", "")
        .replace(",", "")
    )
    if not normalized:
        return {}
    if len(normalized) % 2:
        raise ValueError("hex input has an odd number of digits")
    try:
        raw = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("hex input contains a non-hexadecimal character") from exc

    result = {
        "Byte count": str(len(raw)),
        "ASCII": raw.decode("ascii", errors="replace"),
        "UTF-8": raw.decode("utf-8", errors="replace"),
        "UTF-16 LE": raw.decode("utf-16-le", errors="replace") if len(raw) % 2 == 0 else "— (odd byte count)",
        "UTF-16 BE": raw.decode("utf-16-be", errors="replace") if len(raw) % 2 == 0 else "— (odd byte count)",
    }
    for width in (1, 2, 4, 8):
        if len(raw) != width:
            continue
        bits = width * 8
        result[f"Unsigned {bits}-bit LE"] = str(int.from_bytes(raw, "little", signed=False))
        result[f"Signed {bits}-bit LE"] = str(int.from_bytes(raw, "little", signed=True))
        if width > 1:
            result[f"Unsigned {bits}-bit BE"] = str(int.from_bytes(raw, "big", signed=False))
            result[f"Signed {bits}-bit BE"] = str(int.from_bytes(raw, "big", signed=True))
    if len(raw) == 4:
        mac_seconds = int.from_bytes(raw, "little")
        result["Mac epoch timestamp (u32 LE)"] = _mac_epoch_iso(mac_seconds)
    return result


def _mac_epoch_iso(seconds: int) -> str:
    """Render an unsigned 1904-epoch timestamp without local-time ambiguity."""
    from datetime import UTC, datetime, timedelta

    return (datetime(1904, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).isoformat()
