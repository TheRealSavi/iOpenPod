"""MHIA (Album Item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhiaHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    album_id: int = cf(0x10, "u32")
    sql_id: int = cf(0x14, "u64")
    content_type_flag: int = cf(0x1C, "u16", default=2)
    album_compilation_flag: int = cf(0x1E, "u16")
    album_track_db_id: int = cf(0x20, "u64")
    album_rating: int = cf(0x28, "u8")
    rating_flag: int = cf(0x29, "u8")
    season_number: int = cf(0x2C, "u32")


DEFINITION: ChunkDefinition[MhiaHeader] = ChunkDefinition(
    marker=b"mhia",
    purpose="iTunesDB album item",
    header_type=MhiaHeader,
    minimum_header_size=16,
    header_sizes=(88,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)
