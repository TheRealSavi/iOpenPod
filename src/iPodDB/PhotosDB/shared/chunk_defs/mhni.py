"""MHNI (photo image name/location) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhniHeader] = ChunkDefinition(
    marker=b"mhni",
    purpose="Photo image location and dimensions",
    header_type=MhniHeader,
    minimum_header_size=44,
    header_sizes=(76,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)

__all__ = ["DEFINITION", "MhniHeader"]
