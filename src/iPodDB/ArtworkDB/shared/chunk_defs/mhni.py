"""MHNI (ArtworkDB image name/location) Chunk definition."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhniHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    format_id: int = cf(0x10, "u32")
    ithmb_offset: int = cf(0x14, "u32")
    image_size: int = cf(0x18, "u32")  # Native pixel-file read length.
    vertical_padding: int = cf(0x1C, "i16")
    horizontal_padding: int = cf(0x1E, "i16")
    image_height: int = cf(0x20, "u16")
    image_width: int = cf(0x22, "u16")
    # Raw serialized playback-position key, not a cursor's transformed key.
    # Preserve 0xffffffff and never apply the firmware cursor's +1 on disk.
    image_time_key: int = cf(0x24, "u32")
    # Retained allocation size (Host interpretation), never a read-length fallback.
    image_size_2: int = cf(0x28, "u32")


DEFINITION: ChunkDefinition[MhniHeader] = ChunkDefinition(
    marker=b"mhni",
    purpose="Artwork image location and dimensions",
    header_type=MhniHeader,
    minimum_header_size=44,
    header_sizes=(76,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker}),),
)
