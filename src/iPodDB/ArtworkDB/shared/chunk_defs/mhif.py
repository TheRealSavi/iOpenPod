"""MHIF (ArtworkDB file-format item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhifHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    format_id: int = cf(0x10, "u32")
    image_size: int = cf(0x14, "u32")


DEFINITION: ChunkDefinition[MhifHeader] = ChunkDefinition(
    marker=b"mhif",
    purpose="Artwork file-format item",
    header_type=MhifHeader,
    minimum_header_size=24,
    header_sizes=(124,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)
