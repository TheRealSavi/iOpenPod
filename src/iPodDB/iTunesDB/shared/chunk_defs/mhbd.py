from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhbdHeader(ChunkHeader):
    compressed: int = cf(0x0C, "u32", default=1)
    version: int = cf(0x10, "u32", default=0xFF)
    child_count: int = cf(0x14, "u32", counts_children=True)
    db_id: int = cf(0x18, "u64")
    platform: int = cf(0x20, "u16", default=2)
    unk_mhbd_0x22: int = cf(0x22, "u16", default=0)
    db_id_2: int = cf(0x24, "u64")
    unk_mhbd_0x2c: int = cf(0x2C, "u32")
    hashing_scheme: int = cf(0x30, "u16")
    unk0x32: bytes = cf(0x32, "raw", size=20)
    language: bytes = cf(0x46, "raw", size=2, default=b"en")
    db_persistent_id: int = cf(0x48, "u64")
    unk_mhbd_0x50: int = cf(0x50, "u32", default=1)
    unk_mhbd_0x54: int = cf(0x54, "u32", default=15)
    hash58: bytes = cf(0x58, "raw", size=20)
    timezone_offset: int = cf(0x6C, "i32")
    hash_type_indicator: int = cf(0x70, "u16")
    hash72: bytes = cf(0x72, "raw", size=46)
    # Extended fields — only in newer database headers.
    audio_language: int = cf(0xA0, "u16")
    subtitle_language: int = cf(0xA2, "u16")
    unk_mhbd_0xa4: int = cf(0xA4, "u16")
    unk_mhbd_0xa6: int = cf(0xA6, "u16")
    cdb_flag: int = cf(0xA8, "u16")
    hashab: bytes = cf(0xAB, "raw", size=57)


DEFINITION: ChunkDefinition[MhbdHeader] = ChunkDefinition(
    marker=b"mhbd",
    purpose="iTunesDB root",
    header_type=MhbdHeader,
    minimum_header_size=24,
    header_sizes=(244,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(frozenset({MHSD_DEFINITION.marker}),),
)
