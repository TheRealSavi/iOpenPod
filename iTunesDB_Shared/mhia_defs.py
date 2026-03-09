"""MHIA (Album Item) field definitions.

Declarative :class:`FieldDef` list for the MHIA chunk — an album
record inside an MHLA (album list).
"""

from .field_base import FieldDef, _u32, _u16, _u64

_S = "mhia"

MHIA_HEADER_SIZE: int = 88

MHIA_FIELDS: list[FieldDef] = [
    _u32("child_count", 0x0C, section_type=_S),
    _u32("album_id", 0x10, section_type=_S, required=True),
    _u64("sql_id", 0x14, section_type=_S),
    _u16("platform_flag", 0x1C, section_type=_S, default=2),
    _u16("album_compilation_flag", 0x1E, section_type=_S),
    # Representative track db_id — only populated by some iTunes versions
    _u64("album_track_db_id", 0x20, section_type=_S, min_header_length=0x28),
]
