"""MHOD type 53 library jump-table definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import BinaryStruct, MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodLibraryJumpTablePrefix(MhodPayloadPrefix):
    sort_type: int = cf(0x18, "u32")
    entry_count: int = cf(0x1C, "u32")
    padding_0x20: bytes = cf(0x20, "raw", size=8)


@dataclass(frozen=True, slots=True)
class MhodLibraryJumpTableEntry(BinaryStruct):
    letter_code: int = cf(0x00, "u16")
    padding_0x02: int = cf(0x02, "u16")
    start_index: int = cf(0x04, "u32")
    entry_count: int = cf(0x08, "u32")


@dataclass(frozen=True, slots=True)
class MhodLibraryJumpTablePayload(MhodPayload):
    entries: tuple[MhodLibraryJumpTableEntry, ...]
    trailing_data: bytes
