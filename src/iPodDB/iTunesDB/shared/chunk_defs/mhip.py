"""MHIP (Playlist Item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhipHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    podcast_group_flag: int = cf(0x10, "u16")
    unk_mhip_0x12: int = cf(0x12, "u16")
    group_id: int = cf(0x14, "u32")
    track_id: int = cf(0x18, "u32")
    timestamp: int = cf(0x1C, "u32")
    group_id_ref: int = cf(0x20, "u32")
    group_persistent_id: int = cf(0x24, "u64")
    track_persistent_id: int = cf(0x2C, "u64")
    mhip_persistent_id: int = cf(0x3C, "u64")


DEFINITION: ChunkDefinition[MhipHeader] = ChunkDefinition(
    marker=b"mhip",
    purpose="iTunesDB playlist item",
    header_type=MhipHeader,
    minimum_header_size=16,
    header_sizes=(76,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)
