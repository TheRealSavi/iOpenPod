"""Data models for the analysis pipeline.

All intermediate representations flow through these classes:
  raw binary → ParsedDatabase → UnknownRegion → hypotheses
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ChunkRecord:
    """A single parsed chunk with byte-coverage metadata."""
    chunk_type: str                     # e.g. "mhit", "mhyp"
    abs_offset: int                     # absolute byte offset in file
    header_length: int
    total_length: int                   # header + body + children
    parsed_fields: dict[str, Any]       # field_name → parsed value
    children: list[ChunkRecord] = field(default_factory=list)
    raw_header: bytes = b""             # raw header bytes for re-analysis

    @property
    def abs_end(self) -> int:
        return self.abs_offset + self.total_length


@dataclass
class UnknownRegion:
    """A byte range inside a chunk header that the parser does not cover."""
    chunk_type: str                     # parent chunk type
    chunk_offset: int                   # absolute offset of the parent chunk
    rel_offset: int                     # offset within the chunk header
    length: int                         # bytes
    raw_bytes: bytes                    # the actual unknown bytes
    header_length: int                  # parent chunk's header_length

    @property
    def abs_offset(self) -> int:
        return self.chunk_offset + self.rel_offset

    @property
    def rel_end(self) -> int:
        return self.rel_offset + self.length

    def as_hex(self) -> str:
        return self.raw_bytes.hex()


@dataclass
class ParsedDatabase:
    """Complete structured representation of one iTunesDB file."""
    file_path: str
    file_size: int
    db_version: int                     # mhbd.version
    db_version_name: str
    platform: int                       # 1=Mac, 2=Windows
    hashing_scheme: int
    root: ChunkRecord                   # mhbd root
    all_chunks: list[ChunkRecord] = field(default_factory=list)
    unknowns: list[UnknownRegion] = field(default_factory=list)

    @property
    def track_count(self) -> int:
        return sum(1 for c in self.all_chunks if c.chunk_type == "mhit")

    @property
    def mhit_header_length(self) -> Optional[int]:
        """Header length of the first mhit (determines schema version)."""
        for c in self.all_chunks:
            if c.chunk_type == "mhit":
                return c.header_length
        return None


@dataclass
class ValueObservation:
    """A value seen at a specific unknown offset across files."""
    chunk_type: str
    rel_offset: int
    length: int
    raw_bytes: bytes
    file_path: str
    db_version: int

    @property
    def as_u32_le(self) -> Optional[int]:
        if self.length == 4:
            return int.from_bytes(self.raw_bytes, "little", signed=False)
        return None

    @property
    def as_i32_le(self) -> Optional[int]:
        if self.length == 4:
            return int.from_bytes(self.raw_bytes, "little", signed=True)
        return None

    @property
    def as_u16_le(self) -> Optional[int]:
        if self.length >= 2:
            return int.from_bytes(self.raw_bytes[:2], "little", signed=False)
        return None

    @property
    def as_u64_le(self) -> Optional[int]:
        if self.length == 8:
            return int.from_bytes(self.raw_bytes, "little", signed=False)
        return None

    @property
    def is_all_zero(self) -> bool:
        return all(b == 0 for b in self.raw_bytes)
