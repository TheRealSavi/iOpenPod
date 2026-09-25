"""MHIF (photo file-format item) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhifHeader] = ChunkDefinition(
    marker=b"mhif",
    purpose="Photo file-format item",
    header_type=MhifHeader,
    minimum_header_size=24,
    header_sizes=(124,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)

__all__ = ["DEFINITION", "MhifHeader"]
