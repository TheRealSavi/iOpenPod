"""MHLI (Photo Database image list) Chunk definition."""

from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[EmptyChunkHeader] = ChunkDefinition(
    marker=b"mhli",
    purpose="Photo image list",
    header_type=EmptyChunkHeader,
    minimum_header_size=12,
    header_sizes=(92,),
    extent_type="child_count",
    body_kind="children",
    child_marker_groups=(frozenset({MHII_DEFINITION.marker}),),
)
