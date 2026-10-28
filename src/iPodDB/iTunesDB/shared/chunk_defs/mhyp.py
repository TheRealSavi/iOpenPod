"""MHYP (Playlist) Chunk definition."""

from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.shared.chunk import ChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class MhypHeader(ChunkHeader):
    mhod_child_count: int = cf(0x0C, "u32", counts_children=True)
    mhip_child_count: int = cf(0x10, "u32", counts_children=True)
    master_flag: int = cf(0x14, "u8")
    # Classic 2.0.1: bit 0 selects shuffle traversal; other bits are unresolved.
    shuffle_flags: int = cf(0x15, "u8")
    flag_2: int = cf(0x16, "u8")
    # Classic copies bit 0 to native list +0x150 bit 2; its role is unresolved.
    flag_3: int = cf(0x17, "u8")
    timestamp: int = cf(0x18, "u32")
    playlist_id: int = cf(0x1C, "u64")
    unk_mhyp_0x24: int = cf(0x24, "u32")
    # Classic 2.0.1: 0 preserves the existing mode; 1/off, 2/one, 3/all;
    # other nonzero values map to off. Preserve the full raw u16, including
    # unknown values. This is not the native or player-facing repeat enum.
    # See docs/research/unknown-field-reconciliation.md for the scoped evidence.
    serialized_repeat_override: int = cf(0x28, "u16", default=1)
    playlist_kind_flags: int = cf(0x2A, "u16")
    sort_order: int = cf(0x2C, "u32")
    parent_folder_playlist_id: int = cf(0x30, "u64")
    # Copied to Classic's native list +0x1C0; the destination role is unresolved.
    unk_mhyp_0x38: int = cf(0x38, "u32")
    # extended header fields
    db_id_2: int = cf(0x3C, "u64")
    playlist_id_2: int = cf(0x44, "u64")
    unk_mhyp_0x4C: int = cf(0x4C, "u32")
    mhsd_5_type: int = cf(0x50, "u16")
    phase_game_flag: int = cf(0x52, "u16")
    unk_mhyp_0x54: bytes = cf(0x54, "raw", size=4)
    timestamp_2: int = cf(0x58, "u32")


DEFINITION: ChunkDefinition[MhypHeader] = ChunkDefinition(
    marker=b"mhyp",
    purpose="iTunesDB playlist",
    header_type=MhypHeader,
    minimum_header_size=20,
    header_sizes=(184,),
    extent_type="length",
    body_kind="children",
    child_marker_groups=(
        frozenset({MHOD_DEFINITION.marker}),
        frozenset({MHIP_DEFINITION.marker}),
    ),
)
