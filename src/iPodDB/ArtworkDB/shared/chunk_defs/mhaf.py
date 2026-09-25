"""MHAF Chunk with an as-yet unknown ArtworkDB body."""

from dataclasses import dataclass

from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhafHeader(ChunkHeader):
    pass


DEFINITION: ChunkDefinition[MhafHeader] = ChunkDefinition(
    marker=b"mhaf",
    purpose="Opaque ArtworkDB data",
    header_type=MhafHeader,
    minimum_header_size=12,
    header_sizes=(12,),
    extent_type="length",
    body_kind="opaque",
    child_marker_groups=(),
)
