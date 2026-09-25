"""MHBA (photo album) Chunk definition."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhbaHeader(ChunkHeader):
    mhod_child_count: int = cf(0x0C, "u32", counts_children=True)
    image_child_count: int = cf(0x10, "u32", counts_children=True)
    album_id: int = cf(0x14, "u32")
    unk_mhba_0x18: int = cf(0x18, "u32")
    unk_mhba_0x1c: int = cf(0x1C, "u16")
    album_type: int = cf(0x1E, "u8")
    play_music: int = cf(0x1F, "u8")
    repeat: int = cf(0x20, "u8")
    random: int = cf(0x21, "u8")
    show_titles: int = cf(0x22, "u8")
    transition_direction: int = cf(0x23, "u8")
    slide_duration: int = cf(0x24, "u32")
    transition_duration: int = cf(0x28, "u32")
    unk_mhba_0x2c: bytes = cf(0x2C, "raw", size=8)
    db_track_id_ref: int = cf(0x34, "u64")
    previous_album_id: int = cf(0x3C, "u32")


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
