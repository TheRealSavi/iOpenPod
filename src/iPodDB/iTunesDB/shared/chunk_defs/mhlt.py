"""MHLT (iTunesDB track list) Chunk definition."""

from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT_DEFINITION
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[EmptyChunkHeader] = ChunkDefinition(
    marker=b"mhlt",
    purpose="iTunesDB track list",
    header_type=EmptyChunkHeader,
    minimum_header_size=12,
    header_sizes=(92,),
    extent_type="child_count",
    body_kind="children",
    child_marker_groups=(frozenset({MHIT_DEFINITION.marker}),),
)
