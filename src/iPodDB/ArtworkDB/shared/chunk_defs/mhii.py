"""MHII (ArtworkDB image item) Chunk definition."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhaf import DEFINITION as MHAF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhiiHeader(ChunkHeader):
    child_count: int = cf(0x0C, "u32", counts_children=True)
    image_id: int = cf(0x10, "u32")
    db_track_id_ref: int = cf(0x14, "u64")
    # Ignored by Classic 120GB 2.0.1's built-in ArtworkDB/PhotosDB paths:
    # discarded with the temporary header, with no later native/API reread.
    # Preserve the bytes; this conclusion is not verified for other firmware.
    unk_mhii_0x1c: int = cf(0x1C, "u32")
    rating: int = cf(0x20, "u32")
    # Copied to parent image +0x1c; ascending unsigned primary key for native
    # ordered image enumeration. Ties use image ID, then native pointer address.
    # See docs/research/mhii-image-field-followup.md.
    image_order_key: int = cf(0x24, "u32")
    original_date: int = cf(0x28, "u32")
    exif_taken_date: int = cf(0x2C, "u32")
    source_image_size: int = cf(0x30, "u32")


DEFINITION: ChunkDefinition[MhiiHeader] = ChunkDefinition(
    marker=b"mhii",
    purpose="Artwork image item",
    header_type=MhiiHeader,
    minimum_header_size=52,
    header_sizes=(152,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHOD_DEFINITION.marker, MHAF_DEFINITION.marker}),),
)
