"""Root fields with retained raw storage and qualified Classic observations.

See docs/research/unknown-field-reconciliation.md for evidence and open meanings.
"""

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
    platform: int = cf(0x20, "u8", default=2)
    # Classic's played marker uses a strict bookmark-percentage comparison.
    # Preserve the entire byte, including values above an ordinary percentage.
    played_mark_threshold_percent: int = cf(0x21, "u8")
    # Independent bytes: copied to TrackStore +0x905/+0x906 and returned by
    # separate game-library getters. Their semantic meanings remain unresolved.
    unk_mhbd_0x22: int = cf(0x22, "u8")
    unk_mhbd_0x23: int = cf(0x23, "u8")
    db_id_2: int = cf(0x24, "u64")
    unk_mhbd_0x2c: int = cf(0x2C, "u32")
    hashing_scheme: int = cf(0x30, "u16")
    # Classic's legacy authentication normalizes this range to zero in the
    # digest input. Its stored purpose is unresolved; retain the original bytes.
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
    # Classic 2.0.1 Genius generator: stop when collected occurrence count
    # equals this target, or when candidates are exhausted. Zero is literal.
    # See docs/research/unknown-itunesdb-field-consumers.md for traced consumers.
    genius_target_count: int = cf(0xA4, "u16")
    # Minimum collected count for a successful result (unsigned >= comparison).
    # Independent of the target; no inferred defaults or cross-field constraints.
    genius_minimum_count: int = cf(0xA6, "u16")
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
