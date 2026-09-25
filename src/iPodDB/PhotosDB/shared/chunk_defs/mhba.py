"""MHBA (photo album) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhbaHeader] = ChunkDefinition(
    marker=b"mhba",
    purpose="Photo album",
    header_type=MhbaHeader,
    minimum_header_size=64,
    header_sizes=(148,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(
        frozenset({MHOD_DEFINITION.marker}),
        frozenset({MHIA_DEFINITION.marker}),
    ),
)

__all__ = ["DEFINITION", "MhbaHeader"]
