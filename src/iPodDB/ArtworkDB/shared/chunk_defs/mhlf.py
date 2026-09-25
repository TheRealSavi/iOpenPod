"""MHLF (ArtworkDB file-format list) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhif import DEFINITION as MHIF_DEFINITION
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[EmptyChunkHeader] = ChunkDefinition(
    marker=b"mhlf",
    purpose="Artwork file-format list",
    header_type=EmptyChunkHeader,
    minimum_header_size=12,
    header_sizes=(92,),
    extent_type="child_count",
    body_kind="children",
    child_marker_groups=(frozenset({MHIF_DEFINITION.marker}),),
)
