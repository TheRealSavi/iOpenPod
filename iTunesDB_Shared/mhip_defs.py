"""MHIP (Playlist Item) field definitions.

Declarative :class:`FieldDef` list for the MHIP chunk — a playlist
entry that references a track by ``track_id``.
"""

from .field_base import FieldDef, _u32, _u16, _u64, mac_to_unix, unix_to_mac

_S = "mhip"

MHIP_HEADER_SIZE: int = 76

MHIP_FIELDS: list[FieldDef] = [
    _u32("child_count", 0x0C, section_type=_S),
    _u16("podcast_group_flag", 0x10, section_type=_S),
    _u16("unk0x12", 0x12, section_type=_S),
    _u32("group_id", 0x14, section_type=_S),
    _u32("track_id", 0x18, section_type=_S, required=True),
    _u32("timestamp", 0x1C, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u32("group_id_ref", 0x20, section_type=_S),
    # Extended (header_length >= 0x34)
    _u64("track_persistent_id", 0x2C, section_type=_S, min_header_length=0x34),
    # Extended (header_length >= 0x44) — per-track persistent ID, absent in older iTunes
    _u64("mhip_persistent_id", 0x3C, section_type=_S, min_header_length=0x44),
]
