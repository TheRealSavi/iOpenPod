"""MHOD type 52 library-index definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodLibraryIndexPrefix(MhodPayloadPrefix):
    sort_type: int = cf(0x18, "u32")
    entry_count: int = cf(0x1C, "u32")
    padding_0x20: bytes = cf(0x20, "raw", size=40)


@dataclass(frozen=True, slots=True)
class MhodLibraryIndexPayload(MhodPayload):
    indices: tuple[int, ...]
    trailing_data: bytes
