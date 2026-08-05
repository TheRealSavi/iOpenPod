"""MHYP (Playlist) field definitions.

Declarative :class:`FieldDef` list for the MHYP chunk — a single
playlist record.
"""

from .field_base import FieldDef, _u8, _u16, _u32, _u64, mac_to_unix, unix_to_mac

_S = "mhyp"

MHYP_HEADER_SIZE: int = 184

MHYP_FIELDS: list[FieldDef] = [
    _u32("mhod_child_count", 0x0C, section_type=_S),
    _u32("mhip_child_count", 0x10, section_type=_S),
    # The 2.0.1 loader uses this branch while constructing the playlist object.
    _u8("master_flag", 0x14, section_type=_S),
    # Classic 6.5G snapshot: 1 in four duplicate rows. The loader copies low
    # bit 0 to a runtime playlist flag; semantic name remains unknown.
    _u8("flag1", 0x15, section_type=_S),
    # Classic 6.5G snapshot: zero in all 173 headers.
    _u8("flag2", 0x16, section_type=_S),
    # Classic 6.5G snapshot: zero in all 173 headers. The loader maps low bit
    # 0 to runtime playlist bit 0x4, so retain it despite this sample's zeros.
    _u8("flag3", 0x17, section_type=_S),
    _u32("timestamp", 0x18, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u64("playlist_id", 0x1C, section_type=_S),
    _u32("unk0x24", 0x24, section_type=_S),
    _u16("string_mhod_child_count", 0x28, section_type=_S),
    # Classic 6.5G snapshot: 0x0100 on 12 rows and 1 on two. Firmware parser
    # 0x0807DD8C only copies bit 0 into its runtime playlist flag.
    _u16("podcast_flag", 0x2A, section_type=_S),
    # The 2.0.1 loader converts non-zero values through FUN_080BFAFC before
    # writing a runtime sort/configuration field.
    _u32("sort_order", 0x2C, section_type=_S),
    # 146 of 173 Classic 6.5G rows contain one of six non-zero IDs here. Each
    # is another MHYP playlist_id with podcast_flag=0x0100; 0x0807DD8C consumes
    # this pair of u32s. Preserve as an opaque playlist-reference candidate.
    _u64("unk0x30_playlist_ref", 0x30, section_type=_S, default=0),
    # Classic 6.5G snapshot (2026-08-04): zero in all 173 MHYP headers. The
    # 2.0.1 loader still copies this u32 to runtime playlist offset +0x1C0.
    _u32("unk0x38", 0x38, section_type=_S, default=0),
    # Extended
    _u64("db_id_2", 0x3C, section_type=_S, min_header_length=0x44),
    _u64("playlist_id_2", 0x44, section_type=_S, min_header_length=0x4C),
    # Classic 6.5G snapshot (2026-08-04): zero in all 173 MHYP headers.
    _u32("unk0x4C", 0x4C, section_type=_S, min_header_length=0x50, default=0),
    # Non-zero values identify the built-in Movies=2, TV Shows=3, Music=4,
    # Books=5, and Rentals=7 playlist rows in the Classic 6.5G snapshot.
    _u16("mhsd5_type", 0x50, section_type=_S, min_header_length=0x52),
    # Provisional historical name: it matches mhsd5_type on the five non-zero
    # category rows, but otherwise is 0x100 (88), 0x10B (2), 0x19 (2), or 0.
    _u16("phase_game_flag", 0x52, section_type=_S, min_header_length=0x54),
    # Classic 6.5G snapshot: 0x01000000 on 48 rows and 1 on one; its unusual
    # byte pattern means this should be retained as an opaque u32.
    _u32("mhsd5_special_flag", 0x54, section_type=_S, min_header_length=0x58),
    _u32("timestamp_2", 0x58, section_type=_S, min_header_length=0x5C,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
]
