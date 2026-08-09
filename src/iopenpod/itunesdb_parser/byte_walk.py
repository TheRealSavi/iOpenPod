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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sys import getsizeof
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
class ByteWalkDocumentIndex:
    """Chunk entries plus direct-parent relationships for a byte-walk file."""

    entries: list[ByteWalkChunkIndexEntry]
    children_by_parent: dict[int, tuple[ByteWalkChunkIndexEntry, ...]]


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

    Cache accounting is based on the retained Python object graph rather than
    source-file length, because decoded JSON can be much larger than its input.
    Clearing the cache invalidates loads that were still running, so an old
    document cannot repopulate it after the user has opened another one.
    """

    def __init__(self, *, max_entries: int = 16, max_bytes: int = 16 * 1024 * 1024) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, Path, int], tuple[dict[str, Any], int]] = OrderedDict()
        self._in_flight: dict[tuple[str, Path, int], _ChunkLoadInFlight] = {}
        self._cached_bytes = 0
        self._generation = 0
        self._lock = RLock()

    def clear(self) -> None:
        """Discard all cached chunks, normally after opening another document."""
        with self._lock:
            self._items.clear()
            self._in_flight.clear()
            self._cached_bytes = 0
            self._generation += 1

    def load(
        self,
        path: str | Path,
        entry: ByteWalkChunkIndexEntry,
    ) -> ByteWalkChunkLoad:
        """Load *entry*, returning it with whether it was served from cache."""
        return self._load(
            path,
            entry,
            "full",
            lambda: load_indexed_chunk(path, entry),
        )

    def load_outline(
        self,
        path: str | Path,
        entry: ByteWalkChunkIndexEntry,
        children: tuple[ByteWalkChunkIndexEntry, ...],
    ) -> ByteWalkChunkLoad:
        """Load a chunk's direct spans without materializing descendant chunks."""
        return self._load(
            path,
            entry,
            "outline",
            lambda: load_indexed_chunk_outline(path, entry, children),
        )

    def _load(
        self,
        path: str | Path,
        entry: ByteWalkChunkIndexEntry,
        kind: str,
        loader: Callable[[], dict[str, Any]],
    ) -> ByteWalkChunkLoad:
        key = (kind, Path(path).resolve(), entry.json_offset)
        with self._lock:
            generation = self._generation
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
            chunk = loader()
        except BaseException as exc:
            with self._lock:
                in_flight.error = exc
                in_flight.completed.set()
                if self._in_flight.get(key) is in_flight:
                    self._in_flight.pop(key)
            raise
        self._store(key, chunk, generation)
        with self._lock:
            in_flight.chunk = chunk
            in_flight.completed.set()
            if self._in_flight.get(key) is in_flight:
                self._in_flight.pop(key)
        return ByteWalkChunkLoad(chunk, was_cached=False)

    def _store(
        self,
        key: tuple[str, Path, int],
        chunk: dict[str, Any],
        generation: int,
    ) -> None:
        """Cache a chunk when it fits, evicting least-recently-used entries."""
        with self._lock:
            if generation != self._generation:
                return
        estimated_size = _estimate_cache_bytes(chunk)
        if estimated_size > self._max_bytes:
            return
        with self._lock:
            if generation != self._generation:
                return
            existing = self._items.pop(key, None)
            if existing is not None:
                self._cached_bytes -= existing[1]
            self._items[key] = (chunk, estimated_size)
            self._cached_bytes += estimated_size
            while self._items and (len(self._items) > self._max_entries or self._cached_bytes > self._max_bytes):
                _, (_, evicted_size) = self._items.popitem(last=False)
                self._cached_bytes -= evicted_size


def _estimate_cache_bytes(value: object, seen: set[int] | None = None) -> int:
    """Estimate the retained size of a cache value without serializing it."""
    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return 0
    seen.add(value_id)
    size = getsizeof(value)
    if isinstance(value, dict):
        return size + sum(
            _estimate_cache_bytes(key, seen) + _estimate_cache_bytes(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return size + sum(_estimate_cache_bytes(item, seen) for item in value)
    if isinstance(value, ByteWalkChunkIndexEntry):
        return size + _estimate_cache_bytes(value.chunk_type, seen) + _estimate_cache_bytes(value.caption, seen)
    return size


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


def build_chunk_hierarchy(
    entries: list[ByteWalkChunkIndexEntry],
) -> dict[int, tuple[ByteWalkChunkIndexEntry, ...]]:
    """Return each chunk's immediate children from their source-byte ranges."""
    children: dict[int, list[ByteWalkChunkIndexEntry]] = {entry.json_offset: [] for entry in entries}
    stack: list[ByteWalkChunkIndexEntry] = []
    for entry in sorted(entries, key=lambda item: (item.file_offset, -item.byte_length, item.json_offset)):
        while stack and not _contains_chunk(stack[-1], entry):
            stack.pop()
        if stack:
            children[stack[-1].json_offset].append(entry)
        stack.append(entry)
    return {parent_offset: tuple(items) for parent_offset, items in children.items()}


def index_byte_walk_document(path: str | Path) -> ByteWalkDocumentIndex:
    """Build the searchable index and direct-child map off the GUI thread."""
    entries = index_byte_walk_json(path)
    return ByteWalkDocumentIndex(entries, build_chunk_hierarchy(entries))


def _contains_chunk(parent: ByteWalkChunkIndexEntry, child: ByteWalkChunkIndexEntry) -> bool:
    """Whether *child* occupies a strict subrange of *parent* in the source DB."""
    if parent is child:
        return False
    parent_end = parent.file_offset + parent.byte_length
    child_end = child.file_offset + child.byte_length
    return parent.file_offset <= child.file_offset and child_end <= parent_end


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


def load_indexed_chunk_outline(
    path: str | Path,
    entry: ByteWalkChunkIndexEntry,
    children: tuple[ByteWalkChunkIndexEntry, ...],
) -> dict[str, Any]:
    """Load direct byte spans and child references without parsing descendants.

    Chunks with children list their header spans first, followed by their nested
    chunks.  Once the first nested entry is reached, the caller's pre-built
    index supplies lightweight child references rather than deserializing their
    JSON objects.  Leaf chunks have no children and are loaded in full only
    when the user explicitly expands them.
    """
    source = Path(path)
    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        direct_entries = _leading_direct_entries(data, entry.json_offset, stop_at_nested=bool(children))
    child_references = [_child_reference(entry, child) for child in children]
    return {
        "chunk": entry.chunk_type,
        "caption": entry.caption,
        "file_offset": f"0x{entry.file_offset:X}",
        "byte_length": entry.byte_length,
        "bytes": [*direct_entries, *child_references],
    }


def _leading_direct_entries(
    data: mmap.mmap,
    object_offset: int,
    *,
    stop_at_nested: bool,
) -> list[dict[str, Any]]:
    """Read leading leaf entries from a chunk's ``bytes`` array only."""
    bytes_marker = data.find(b'"bytes": [', object_offset, min(len(data), object_offset + 16_384))
    if bytes_marker < 0:
        raise ValueError("byte-walk chunk is missing its bytes array")
    cursor = bytes_marker + len(b'"bytes": [')
    entries: list[dict[str, Any]] = []
    while cursor < len(data):
        cursor = _skip_json_array_delimiters(data, cursor)
        if cursor >= len(data) or data[cursor] == ord("]"):
            return entries
        if data[cursor] != ord("{"):
            raise ValueError("byte-walk bytes array contains an invalid entry")
        if stop_at_nested and _entry_starts_nested_chunk(data, cursor):
            return entries
        object_end = _object_end(data, cursor)
        parsed = json.loads(data[cursor:object_end].decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("byte-walk bytes array contains a non-object entry")
        entries.append(parsed)
        cursor = object_end
    raise ValueError("unterminated byte-walk bytes array")


def _skip_json_array_delimiters(data: mmap.mmap, cursor: int) -> int:
    """Advance past whitespace and commas between JSON array elements."""
    while cursor < len(data) and data[cursor] in b" \t\r\n,":
        cursor += 1
    return cursor


def _entry_starts_nested_chunk(data: mmap.mmap, object_offset: int) -> bool:
    """Return whether the current array item is a nested chunk reference.

    The check walks only the current item's top-level properties.  In
    particular, it returns as soon as it finds a ``chunk`` property and never
    scans into the child object.  A fixed-size text probe would incorrectly
    find the next item's ``chunk`` property while examining a short header
    entry, hiding all of a container's header fields.
    """
    cursor = object_offset + 1
    while cursor < len(data):
        cursor = _skip_json_whitespace(data, cursor)
        if cursor >= len(data) or data[cursor] == ord("}"):
            return False
        if data[cursor] != ord('"'):
            raise ValueError("byte-walk bytes array contains an invalid object key")
        property_name, cursor = _json_string_at(data, cursor)
        cursor = _skip_json_whitespace(data, cursor)
        if cursor >= len(data) or data[cursor] != ord(":"):
            raise ValueError("byte-walk bytes array contains an invalid object property")
        cursor = _skip_json_whitespace(data, cursor + 1)
        if property_name == "chunk":
            return cursor < len(data) and data[cursor] == ord("{")
        cursor = _skip_json_value(data, cursor)
        cursor = _skip_json_whitespace(data, cursor)
        if cursor < len(data) and data[cursor] == ord(","):
            cursor += 1
            continue
        if cursor < len(data) and data[cursor] == ord("}"):
            return False
        raise ValueError("byte-walk bytes array contains an invalid object separator")
    raise ValueError("unterminated byte-walk bytes array")


def _skip_json_whitespace(data: mmap.mmap, cursor: int) -> int:
    """Advance past JSON whitespace without allocating a decoded string."""
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    return cursor


def _skip_json_value(data: mmap.mmap, cursor: int) -> int:
    """Find the end of one JSON value while retaining none of it."""
    depth = 0
    in_string = False
    escaped = False
    while cursor < len(data):
        byte = data[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
        elif byte == ord('"'):
            in_string = True
        elif byte in (ord("{"), ord("[")):
            depth += 1
        elif byte in (ord("}"), ord("]")):
            if depth == 0:
                return cursor
            depth -= 1
        elif byte == ord(",") and depth == 0:
            return cursor
        cursor += 1
    raise ValueError("unterminated JSON value in byte-walk document")


def _child_reference(
    parent: ByteWalkChunkIndexEntry,
    child: ByteWalkChunkIndexEntry,
) -> dict[str, Any]:
    """Represent an indexed child without retaining any of its byte entries."""
    return {
        "at": f"0x{child.file_offset - parent.file_offset:X}",
        "byte_length": child.byte_length,
        "chunk": {
            "chunk": child.chunk_type,
            "caption": child.caption,
            "file_offset": f"0x{child.file_offset:X}",
            "byte_length": child.byte_length,
        },
        "indexed_chunk": child,
    }


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
