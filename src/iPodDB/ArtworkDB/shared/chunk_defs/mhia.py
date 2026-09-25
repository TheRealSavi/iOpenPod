"""MHIA (photo album item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhiaHeader(ChunkHeader):
    image_id: int = cf(0x10, "u32")


DEFINITION: ChunkDefinition[MhiaHeader] = ChunkDefinition(
    marker=b"mhia",
    purpose="Photo album image membership",
    header_type=MhiaHeader,
    minimum_header_size=20,
    header_sizes=(40,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(),
)
