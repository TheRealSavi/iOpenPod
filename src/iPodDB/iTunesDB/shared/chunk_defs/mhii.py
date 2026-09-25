"""MHII (Artist Item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhiiHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    artist_id: int = cf(0x10, "u32")
    sql_id: int = cf(0x14, "u64")
    content_type_flag: int = cf(0x1C, "u32", default=2)


DEFINITION: ChunkDefinition[MhiiHeader] = ChunkDefinition(
    marker=b"mhii",
    purpose="iTunesDB artist item",
    header_type=MhiiHeader,
    minimum_header_size=16,
    header_sizes=(80,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)
