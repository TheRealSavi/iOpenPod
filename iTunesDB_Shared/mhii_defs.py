"""MHII (Artist Item) field definitions.

Declarative :class:`FieldDef` list for the MHII chunk — an artist
record inside an MHLI (artist list, MHSD type 8).
"""

from .field_base import FieldDef, _u32, _u64

_S = "mhii"

MHII_HEADER_SIZE: int = 80

MHII_FIELDS: list[FieldDef] = [
    _u32("child_count", 0x0C, section_type=_S),
    _u32("artist_id", 0x10, section_type=_S, required=True),
    _u64("sql_id", 0x14, section_type=_S),
    _u32("platform_flag", 0x1C, section_type=_S, default=2),
]
