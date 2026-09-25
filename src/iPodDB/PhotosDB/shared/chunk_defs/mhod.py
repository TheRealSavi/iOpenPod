"""Photo Database MHOD common Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhodHeader] = ChunkDefinition(
    marker=b"mhod",
    purpose="Typed Photo Database data object",
    header_type=MhodHeader,
    minimum_header_size=14,
    header_sizes=(24,),
    extent_type="length",
    body_kind="mhod",
    child_marker_groups=(),
)

__all__ = ["DEFINITION", "MhodHeader"]
