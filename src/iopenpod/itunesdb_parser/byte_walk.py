"""Utilities for navigating iTunesDB byte-walk JSON without loading it all.

The forensic export is deliberately verbose.  A real iTunesDB can therefore
produce a JSON file too large for ``json.load`` or a text editor to handle
comfortably.  This module builds a lightweight index from the on-disk JSON and
loads only the one selected chunk object on demand.
"""

from __future__ import annotations

import json
import mmap
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
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


@dataclass(frozen=True, slots=True)
class ByteWalkChunkLoad:
    """A selected chunk and whether the cache avoided an on-disk parse."""

    chunk: dict[str, Any]
    was_cached: bool


@dataclass(slots=True)
class _ChunkLoadInFlight:
    """Result hand-off for simultaneous requests for one uncached chunk."""

    completed: Event
    chunk: dict[str, Any] | None = None
    error: BaseException | None = None


class ByteWalkChunkCache:
    """Thread-safe, bounded LRU cache for chunks opened by the inspector.

    A byte-walk chunk is a decoded JSON object and can be substantially larger
    than its source bytes.  The cache consequently uses a deliberately high
    multiple of the source length as its budget: frequently inspected small
    chunks stay warm, while a selected database root cannot grow the
    inspector's memory without bound.
    """

    def __init__(self, *, max_entries: int = 16, max_bytes: int = 16 * 1024 * 1024) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._items: OrderedDict[tuple[Path, int], tuple[dict[str, Any], int]] = OrderedDict()
        self._in_flight: dict[tuple[Path, int], _ChunkLoadInFlight] = {}
        self._cached_bytes = 0
        self._lock = RLock()

    def clear(self) -> None:
        """Discard all cached chunks, normally after opening another document."""
        with self._lock:
            self._items.clear()
            self._cached_bytes = 0

    def load(
        self,
        path: str | Path,
        entry: ByteWalkChunkIndexEntry,
    ) -> ByteWalkChunkLoad:
        """Load *entry*, returning it with whether it was served from cache."""
        key = (Path(path).resolve(), entry.json_offset)
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return ByteWalkChunkLoad(cached[0], was_cached=True)
            in_flight = self._in_flight.get(key)
            if in_flight is None:
                in_flight = _ChunkLoadInFlight(Event())
                self._in_flight[key] = in_flight
                is_loader = True
            else:
                is_loader = False

        if not is_loader:
            in_flight.completed.wait()
            if in_flight.error is not None:
                raise in_flight.error
            if in_flight.chunk is None:
                raise RuntimeError("chunk load completed without a result")
            return ByteWalkChunkLoad(in_flight.chunk, was_cached=True)

        try:
            chunk = load_indexed_chunk(path, entry)
        except BaseException as exc:
            with self._lock:
                in_flight.error = exc
                in_flight.completed.set()
                self._in_flight.pop(key, None)
            raise
        self._store(key, chunk, entry.byte_length)
        with self._lock:
            in_flight.chunk = chunk
            in_flight.completed.set()
            self._in_flight.pop(key, None)
        return ByteWalkChunkLoad(chunk, was_cached=False)

    def _store(self, key: tuple[Path, int], chunk: dict[str, Any], byte_length: int) -> None:
        """Cache a chunk when it fits, evicting least-recently-used entries."""
        estimated_size = max(byte_length * 8, 1_024)
        if estimated_size > self._max_bytes:
            return
        with self._lock:
            existing = self._items.pop(key, None)
            if existing is not None:
                self._cached_bytes -= existing[1]
            self._items[key] = (chunk, estimated_size)
            self._cached_bytes += estimated_size
            while self._items and (len(self._items) > self._max_entries or self._cached_bytes > self._max_bytes):
                _, (_, evicted_size) = self._items.popitem(last=False)
                self._cached_bytes -= evicted_size


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
