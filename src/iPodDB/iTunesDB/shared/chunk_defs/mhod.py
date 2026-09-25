"""MHOD common Chunk definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhodHeader(MhodChunkHeader):
    mhod_type: int = cf(0x0C, "u32")
    unk_mhod_0x10: int = cf(0x10, "u32")
    unk_mhod_0x14: int = cf(0x14, "u32")


DEFINITION: ChunkDefinition[MhodHeader] = ChunkDefinition(
    marker=b"mhod",
    purpose="Typed iTunesDB data object",
    header_type=MhodHeader,
    minimum_header_size=16,
    header_sizes=(24,),
    extent_type="length",
    body_kind="mhod",
    child_marker_groups=(),
)
