"""MHIA (photo album item) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.shared.types import ChunkDefinition

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

__all__ = ["DEFINITION", "MhiaHeader"]
