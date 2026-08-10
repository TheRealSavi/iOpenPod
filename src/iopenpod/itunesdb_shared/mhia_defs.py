"""MHIA (Album Item) field definitions.

Declarative :class:`FieldDef` list for the MHIA chunk — an album
record inside an MHLA (album list).
"""

from .field_base import FieldDef, _u8, _u16, _u32, _u64

_S = "mhia"

MHIA_HEADER_SIZE: int = 88

MHIA_FIELDS: list[FieldDef] = [
    _u32("child_count", 0x0C, section_type=_S),
    _u32("album_id", 0x10, section_type=_S, required=True),
    _u64("sql_id", 0x14, section_type=_S),
    # Classic 6.5G snapshot (2026-08-04): 3 is podcast-only (six albums), 4
    # is TV-show-only (14), and 0x102 marks all 18 compilation-music albums;
    # 2 covers the remaining 1,021 albums. This is a content-class field in
    # this sample, despite the inherited platform-oriented name.
    _u16("platform_flag", 0x1C, section_type=_S, default=2),
    # Classic 6.5G snapshot (2026-08-04): zero in all 1,059 records, including
    # the 18 compilation albums identified by platform_flag=0x102.
    _u16("album_compilation_flag", 0x1E, section_type=_S),
    # Classic 6.5G snapshot: non-zero in every album and always matches one
    # member track's db_track_id; a representative-member reference.
    _u64("album_track_db_id", 0x20, section_type=_S, min_header_length=0x28),
    # Values are the normal 0–100 rating scale (454 non-zero albums); 0x20 at
    # +0x29 occurs exactly when this is non-zero. It equals the maximum member
    # track rating in 391/454 rated albums, so retain a cautious album-rating
    # candidate name until its aggregation contract is confirmed.
    _u8("album_rating", 0x28, section_type=_S, default=0),
    _u8("unk0x29_rating_flag", 0x29, section_type=_S, default=0),
    # +0x2A..+0x2B are zero padding in the Classic 6.5G snapshot.
    # Non-zero only on 13 TV-show albums; each value exactly matches every
    # member track's MHIT season_number. This is a confirmed album-level
    # season mirror in the sample.
    _u32("season_number", 0x2C, section_type=_S, default=0),
]
