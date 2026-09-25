"""MHFD (PhotosDB root) Chunk definition."""

from dataclasses import dataclass

from iPodDB.PhotosDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhfdHeader(ChunkHeader):
    """Nominal PhotosDB root using the evidenced MHFD field layout."""

    unk_mhfd_0x0c: int = cf(0x0C, "u32")
    unk_mhfd_0x10: int = cf(0x10, "u32")
    child_count: int = cf(0x14, "u32", counts_children=True)
    unk_mhfd_0x18: int = cf(0x18, "u32")
    next_mhii_id: int = cf(0x1C, "u32")
    unk_mhfd_0x20: int = cf(0x20, "u64")
    unk_mhfd_0x28: int = cf(0x28, "u64")
    unk_mhfd_0x30: int = cf(0x30, "u32", default=2)
    unk_mhfd_0x34: int = cf(0x34, "u32")
    unk_mhfd_0x38: int = cf(0x38, "u32")
    unk_mhfd_0x3c: int = cf(0x3C, "u32")
    unk_mhfd_0x40: int = cf(0x40, "u32")


DEFINITION: ChunkDefinition[MhfdHeader] = ChunkDefinition(
    marker=b"mhfd",
    purpose="PhotosDB root",
    header_type=MhfdHeader,
    minimum_header_size=32,
    header_sizes=(132,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHSD_DEFINITION.marker}),),
)
