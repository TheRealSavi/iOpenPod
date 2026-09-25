"""MHAF Chunk with an as-yet unknown Photo Database body."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhaf import MhafHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhafHeader] = ChunkDefinition(
    marker=b"mhaf",
    purpose="Opaque Photo Database data",
    header_type=MhafHeader,
    minimum_header_size=12,
    header_sizes=(12,),
    extent_type="length",
    body_kind="opaque",
    child_marker_groups=(),
)

__all__ = ["DEFINITION", "MhafHeader"]
