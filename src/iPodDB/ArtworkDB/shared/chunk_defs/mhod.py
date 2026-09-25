"""ArtworkDB MHOD common Chunk definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhodHeader(MhodChunkHeader):
    mhod_type: int = cf(0x0C, "u16")
    unk_mhod_0x0e: int = cf(0x0E, "u8")
    padding_length: int = cf(0x0F, "u8")
    unk_mhod_0x10: bytes = cf(0x10, "raw", size=8)


DEFINITION: ChunkDefinition[MhodHeader] = ChunkDefinition(
    marker=b"mhod",
    purpose="Typed ArtworkDB data object",
    header_type=MhodHeader,
    minimum_header_size=14,
    header_sizes=(24,),
    extent_type="length",
    body_kind="mhod",
    child_marker_groups=(),
)
