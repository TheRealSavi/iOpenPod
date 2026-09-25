"""MHLA (iTunesDB album list) Chunk definition."""

from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[EmptyChunkHeader] = ChunkDefinition(
    marker=b"mhla",
    purpose="iTunesDB album list",
    header_type=EmptyChunkHeader,
    minimum_header_size=12,
    header_sizes=(92,),
    extent_type="child_count",
    body_kind="children",
    child_marker_groups=(frozenset({MHIA_DEFINITION.marker}),),
)
