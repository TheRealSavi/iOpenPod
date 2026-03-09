"""MHBD (Database Header) field definitions.

Declarative :class:`FieldDef` list for the MHBD chunk — the root of
the iTunesDB file.  Both the parser and writer derive their behaviour
from these definitions.
"""

from .field_base import FieldDef, _u32, _i32, _u16, _u64, _raw

_S = "mhbd"

# Writer header size (matching iTunes / libgpod default).
MHBD_HEADER_SIZE: int = 244  # 0xF4

# Named offsets used by hash modules for zeroing before signing.
MHBD_OFFSET_DB_ID: int = 0x18           # 8 bytes (u64)
MHBD_OFFSET_HASHING_SCHEME: int = 0x30  # 2 bytes (u16)
MHBD_OFFSET_UNK_0x32: int = 0x32        # 20 bytes (raw)
MHBD_OFFSET_HASH58: int = 0x58          # 20 bytes (raw)
MHBD_OFFSET_HASH72: int = 0x72          # 46 bytes (raw)
MHBD_OFFSET_HASHAB: int = 0xAB          # 57 bytes (raw)

MHBD_FIELDS: list[FieldDef] = [
    _u32("compressed", 0x0C, section_type=_S, default=1),
    _u32("version", 0x10, section_type=_S, required=True),
    _u32("child_count", 0x14, section_type=_S),
    _u64("db_id", 0x18, section_type=_S, required=True),
    _u16("platform", 0x20, section_type=_S, default=2),
    _u16("unk0x22", 0x22, section_type=_S, default=0),
    _u64("db_id_2", 0x24, section_type=_S),
    _u32("unk0x2c", 0x2C, section_type=_S),
    _u16("hashing_scheme", 0x30, section_type=_S),
    _raw("unk0x32", 0x32, 20, section_type=_S),
    _raw("language", 0x46, 2, section_type=_S, default=b"en"),
    _u64("db_persistent_id", 0x48, section_type=_S),
    _u32("unk0x50", 0x50, section_type=_S, default=1),
    _u32("unk0x54", 0x54, section_type=_S, default=15),
    _raw("hash58", 0x58, 20, section_type=_S),
    _i32("timezone_offset", 0x6C, section_type=_S),
    _u16("hash_type_indicator", 0x70, section_type=_S),
    _raw("hash72", 0x72, 46, section_type=_S),
    # Extended fields — only in newer database headers.
    _u16("audio_language", 0xA0, section_type=_S, min_header_length=0xA2),
    _u16("subtitle_language", 0xA2, section_type=_S, min_header_length=0xA4),
    _u16("unk0xa4", 0xA4, section_type=_S, min_header_length=0xA6),
    _u16("unk0xa6", 0xA6, section_type=_S, min_header_length=0xA8),
    _u16("cdb_flag", 0xA8, section_type=_S, min_header_length=0xAA),
]
