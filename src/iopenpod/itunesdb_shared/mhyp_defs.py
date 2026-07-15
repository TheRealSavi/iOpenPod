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
    _u8("master_flag", 0x14, section_type=_S),
    _u8("flag1", 0x15, section_type=_S),
    _u8("flag2", 0x16, section_type=_S),
    _u8("flag3", 0x17, section_type=_S),
    _u32("timestamp", 0x18, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u64("playlist_id", 0x1C, section_type=_S),
    _u32("unk0x24", 0x24, section_type=_S),
    _u16("string_mhod_child_count", 0x28, section_type=_S),
    _u16("podcast_flag", 0x2A, section_type=_S),
    _u32("sort_order", 0x2C, section_type=_S),
    # Extended
    _u64("db_id_2", 0x3C, section_type=_S, min_header_length=0x44),
    _u64("playlist_id_2", 0x44, section_type=_S, min_header_length=0x4C),
    _u16("mhsd5_type", 0x50, section_type=_S, min_header_length=0x52),
    _u16("mhsd5_type_2", 0x52, section_type=_S, min_header_length=0x54),
    _u32("mhsd5_special_flag", 0x54, section_type=_S, min_header_length=0x58),
    _u32("timestamp_2", 0x58, section_type=_S, min_header_length=0x5C,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
]
