"""MHII (Photo Database image item) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhaf import DEFINITION as MHAF_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.types import ChunkDefinition

DEFINITION: ChunkDefinition[MhiiHeader] = ChunkDefinition(
    marker=b"mhii",
    purpose="Photo image item",
    header_type=MhiiHeader,
    minimum_header_size=52,
    header_sizes=(152,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker, MHAF_DEFINITION.marker}),),
)

__all__ = ["DEFINITION", "MhiiHeader"]
