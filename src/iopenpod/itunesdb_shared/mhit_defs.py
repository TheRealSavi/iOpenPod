"""MHIT (Track Item) field definitions.

Declarative :class:`FieldDef` list for the MHIT chunk — a single track
record.  Both the parser and writer derive their behaviour from these
definitions.
"""

from .field_base import (
    FieldDef,
    _f32,
    _i32,
    _raw,
    _u8,
    _u16,
    _u32,
    _u64,
    clamp_rating,
    fixed_to_sample_rate,
    mac_to_unix,
    sample_rate_to_fixed,
    unix_to_mac,
    validate_rating,
    validate_volume,
)

_S = "mhit"

# Writer header size (iTunes 8+ default).
MHIT_HEADER_SIZE: int = 0x270  # 624 bytes


def mhit_header_size_for_version(db_version: int) -> int:
    """Return the MHIT header size appropriate for *db_version*.

    Older iPod firmware uses smaller MHIT headers.  The writer must pad
    to the correct boundary so the firmware can locate child MHODs.
    """
    if db_version <= 0x12:
        return 0x9C   # 156 — pre-iTunes 7 minimum
    if db_version <= 0x19:
        return 0x148  # 328 — iTunes 7.x
    if db_version <= 0x2D:
        return 0x1F8  # 504 — iTunes 9.x
    return 0x270      # 624 — iTunes 10+ / modern


MHIT_FIELDS: list[FieldDef] = [
    # ── Core fields (always present, minimum header ≥ 0x9C) ──────
    _u32("child_count", 0x0C, section_type=_S),
    _u32("track_id", 0x10, section_type=_S, required=True),
    # Classic 6.5G snapshot (2026-08-04): 1 in every record. The 2.0.1 loader
    # uses values 1, 2, and 3 to select a runtime-object allocation class, so
    # it is live despite not being a discriminator in this library.
    _u32("visible", 0x14, section_type=_S, default=1),
    _u32("filetype", 0x18, section_type=_S),
    _u8("vbr_flag", 0x1C, section_type=_S),
    # Classic 6.5G snapshot: exact mirror of use_podcast_now_playing_flag
    # (both set on the 66 MP3 podcasts). The 2.0.1 loader maps non-zero to
    # runtime bit 0x1, so it is format-sensitive and live here.
    _u8("mp3_flag", 0x1D, section_type=_S),
    # The 2.0.1 loader copies low bit 0 directly into a runtime track flag.
    _u8("compilation_flag", 0x1E, section_type=_S),
    _u8("rating", 0x1F, section_type=_S,
        write_transform=clamp_rating, validator=validate_rating),
    _u32("last_modified", 0x20, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u32("size", 0x24, section_type=_S),
    _u32("length", 0x28, section_type=_S),
    _u32("track_number", 0x2C, section_type=_S),
    _u32("total_tracks", 0x30, section_type=_S),
    _u32("year", 0x34, section_type=_S),
    _u32("bitrate", 0x38, section_type=_S),
    _u32("sample_rate_1", 0x3C, section_type=_S,
         read_transform=fixed_to_sample_rate,
         write_transform=sample_rate_to_fixed),
    _i32("volume", 0x40, section_type=_S, validator=validate_volume),
    _u32("start_time", 0x44, section_type=_S),
    _u32("stop_time", 0x48, section_type=_S),
    _u32("sound_check", 0x4C, section_type=_S),
    _u32("play_count_1", 0x50, section_type=_S),
    _u32("play_count_2", 0x54, section_type=_S),
    _u32("last_played", 0x58, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u32("disc_number", 0x5C, section_type=_S),
    _u32("total_discs", 0x60, section_type=_S),
    _u32("user_id", 0x64, section_type=_S),
    _u32("date_added", 0x68, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u32("bookmark_time", 0x6C, section_type=_S),
    _u64("db_track_id", 0x70, section_type=_S, required=True),
    # Classic 6.5G snapshot (2026-08-04): zero in every record. The 2.0.1
    # loader nevertheless maps its low bit to runtime bit 0x4.
    _u8("checked_flag", 0x78, section_type=_S),
    _u8("app_rating", 0x79, section_type=_S),
    _u16("bpm", 0x7A, section_type=_S),
    _u16("artwork_count", 0x7C, section_type=_S),
    # Classic 6.5G snapshot: 0x80 precisely on the 275 movie_flag records,
    # 0xFFFF otherwise. It is an enumerated format value, not Boolean, and is
    # not visibly promoted by the 2.0.1 MHIT loader.
    _u16("audio_format_flag", 0x7E, section_type=_S, default=0xFFFF),
    _u32("artwork_size", 0x80, section_type=_S),
    _u32("unk0x84", 0x84, section_type=_S),
    _f32("sample_rate_2", 0x88, section_type=_S),
    _u32("date_released", 0x8C, section_type=_S,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u16("mpeg_audio_type", 0x90, section_type=_S),
    _u8("explicit_flag", 0x92, section_type=_S),
    _u8("purchased_aac_flag", 0x93, section_type=_S),
    _u32("unk0x94", 0x94, section_type=_S),
    _u32("genius_category_id", 0x98, section_type=_S),

    # ── Extended fields (guarded by header_length) ───────────────
    _u32("skip_count", 0x9C, section_type=_S, min_header_length=0xA0),
    _u32("last_skipped", 0xA0, section_type=_S, min_header_length=0xA4,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u8("has_artwork", 0xA4, section_type=_S, min_header_length=0xA5),
    _u8("skip_when_shuffling", 0xA5, section_type=_S, min_header_length=0xA6),
    _u8("remember_position", 0xA6, section_type=_S, min_header_length=0xA7),
    _u8("use_podcast_now_playing_flag", 0xA7, section_type=_S, min_header_length=0xA8),
    _u64("db_track_id_2", 0xA8, section_type=_S, min_header_length=0xB0),
    _u8("lyrics_flag", 0xB0, section_type=_S, min_header_length=0xB1),
    _u8("movie_flag", 0xB1, section_type=_S, min_header_length=0xB2),
    # Classic 6.5G snapshot: value 2 in 1,231 records; 1,220 have zero plays
    # and zero last_played, whereas value 1 usually represents played tracks.
    # However, the 2.0.1 loader tests *only* raw value 1 to set runtime bit
    # 0x8. Treat both the inherited name and value-2 correlation as unconfirmed.
    _u8("not_played_flag", 0xB2, section_type=_S, min_header_length=0xB3),
    _u8("unk0xB3", 0xB3, section_type=_S, min_header_length=0xB4),
    # Classic 6.5G snapshot (2026-08-04): all 33 non-zero values exactly
    # mirror bookmark_time. The 2.0.1 MHIT loader does not visibly promote it
    # after its bulk header read; likely a compatibility shadow, unconfirmed.
    _u32("unk0xB4", 0xB4, section_type=_S, min_header_length=0xB8),
    _u32("pregap", 0xB8, section_type=_S, min_header_length=0xBC),
    _u64("sample_count", 0xBC, section_type=_S, min_header_length=0xC4),
    # Classic 6.5G snapshot (2026-08-04): non-zero exactly when lyrics_flag
    # is set (5,864 of 6,541 records). Not visibly promoted by the 2.0.1
    # MHIT loader; high-cardinality opaque lyrics-associated ID.
    _u32("unk0xC4", 0xC4, section_type=_S, min_header_length=0xC8),
    _u32("postgap", 0xC8, section_type=_S, min_header_length=0xCC),
    _u32("encoder", 0xCC, section_type=_S, min_header_length=0xD0),
    _u32("media_type", 0xD0, section_type=_S, min_header_length=0xD4,
         default=1),
    _u32("season_number", 0xD4, section_type=_S, min_header_length=0xD8),
    _u32("episode_number", 0xD8, section_type=_S, min_header_length=0xDC),
    _u32("date_added_to_itunes", 0xDC, section_type=_S, min_header_length=0xE0,
         read_transform=mac_to_unix, write_transform=unix_to_mac),
    _u32("store_track_id", 0xE0, section_type=_S, min_header_length=0xE4),
    _u32("store_encoder_version", 0xE4, section_type=_S, min_header_length=0xE8),
    _u32("store_artist_id", 0xE8, section_type=_S, min_header_length=0xEC),
    # Classic 6.5G snapshot (2026-08-04): non-zero only for music and usually
    # co-occurs with Store metadata. Not visibly promoted by the 2.0.1 MHIT
    # loader; Store-associated u32 with unknown semantics.
    _u32("unk0xEC", 0xEC, section_type=_S, min_header_length=0xF0),
    _u32("store_album_id", 0xF0, section_type=_S, min_header_length=0xF4),
    # Snapshot values are not Boolean (34 distinct non-zero values). Not
    # visibly promoted by the 2.0.1 MHIT loader; retain the inherited name but
    # treat this as a possible packed Store field.
    _u32("store_content_flag", 0xF4, section_type=_S, min_header_length=0xF8),
    _u32("gapless_audio_payload_size", 0xF8, section_type=_S, min_header_length=0xFC),
    _u32("unk0xFC", 0xFC, section_type=_S, min_header_length=0x100),
    # Classic 6.5G snapshot (2026-08-04): every one of 6,541 records is 1.
    # Not visibly promoted by the 2.0.1 MHIT loader, and this sample cannot
    # establish a per-track gapless interpretation.
    _u16("gapless_track_flag", 0x100, section_type=_S, min_header_length=0x102),
    _u16("gapless_album_flag", 0x102, section_type=_S, min_header_length=0x104),
    _raw("hash_0x104", 0x104, 20, section_type=_S, min_header_length=0x118),
    _u32("unk0x118", 0x118, section_type=_S, min_header_length=0x11C),
    _u32("unk0x11C", 0x11C, section_type=_S, min_header_length=0x120),
    _u32("album_id", 0x120, section_type=_S, min_header_length=0x124),
    _u64("db_id_2_ref", 0x124, section_type=_S, min_header_length=0x12C),
    _u32("size_2", 0x12C, section_type=_S, min_header_length=0x130),
    _u32("unk0x130", 0x130, section_type=_S, min_header_length=0x134),
    # Classic 6.5G snapshot: bit 0 exactly matches presence of the respective
    # sort MHOD types 27, 28, 23, 29, 30, and 31 (all 6,541 tracks).
    _raw("sort_mhod_indicators", 0x134, 8, section_type=_S, min_header_length=0x13C),
    # Classic 6.5G snapshot: this Store-associated value is non-zero exactly
    # when purchased_aac_flag is set, and is duplicated at +0x1A0. It is not
    # visibly promoted by the 2.0.1 MHIT loader.
    _u32("unk0x154", 0x154, section_type=_S, min_header_length=0x158, default=0),
    # Gap: 0x13C..0x153 and 0x158..0x15F (zero padding in the Classic sample)
    _u32("artwork_id_ref", 0x160, section_type=_S, min_header_length=0x164),
    # Classic 6.5G snapshot: non-zero in 64 records, all purchased music with
    # artwork. It is not visibly promoted by the 2.0.1 MHIT loader; it may be
    # an upper artwork word, but that relationship has not been confirmed.
    _u32("unk0x164", 0x164, section_type=_S, min_header_length=0x168, default=0),
    # Classic 6.5G snapshot (2026-08-04): 5,820 values are 32 and 721 are 1.
    # Not visibly promoted by the 2.0.1 MHIT loader; candidate feature or
    # provenance value. libgpod always writes 1.
    _u32("unk0x168", 0x168, section_type=_S, min_header_length=0x16C, default=1),
    # Classic 6.5G snapshot: 1 in 180 records. The 2.0.1 MHIT loader directly
    # maps non-zero to runtime track flag 0x1000; the flag's semantic name is
    # still unknown.
    _u8("unk0x173", 0x173, section_type=_S, min_header_length=0x174, default=0),
    # Classic 6.5G snapshot: exact mirror of movie_flag in all 6,541 records.
    # It is not visibly promoted by the 2.0.1 MHIT loader.
    _u8("movie_flag_2", 0x194, section_type=_S, min_header_length=0x195, default=0),
    # Classic 6.5G snapshot: exact mirror of purchased_aac_flag in all records.
    # It is not visibly promoted by the 2.0.1 MHIT loader.
    _u8("purchased_aac_flag_2", 0x195, section_type=_S, min_header_length=0x196,
        default=0),
    # Values are 1 (6,086), 10 (228), 9 (23), or 0 (204); it tracks broad
    # media families but is not a direct mirror of media_type. It is not
    # visibly promoted by the 2.0.1 MHIT loader.
    _u8("unk0x197", 0x197, section_type=_S, min_header_length=0x198, default=0),
    # Exact duplicate of unk0x154 in every Classic 6.5G record. It lies in the
    # loader's initial read but is not visibly promoted into this runtime item.
    _u32("unk0x1A0", 0x1A0, section_type=_S, min_header_length=0x1A4, default=0),
    # A widened Store metadata block. Low words exactly mirror +0xE0..+0xF4;
    # the upper word is 1 on 130 track IDs and 107 album IDs, otherwise zero.
    _u64("store_track_id_2", 0x1B0, section_type=_S, min_header_length=0x1B8,
         default=0),
    _u64("store_encoder_version_2", 0x1B8, section_type=_S, min_header_length=0x1C0,
         default=0),
    _u64("store_artist_id_2", 0x1C0, section_type=_S, min_header_length=0x1C8,
         default=0),
    _u64("unk0xEC_2", 0x1C8, section_type=_S, min_header_length=0x1D0,
         default=0),
    _u64("store_album_id_2", 0x1D0, section_type=_S, min_header_length=0x1D8,
         default=0),
    _u64("store_content_flag_2", 0x1D8, section_type=_S, min_header_length=0x1E0,
         default=0),
    _u32("artist_id_ref", 0x1E0, section_type=_S, min_header_length=0x1E4),
    # Values are 1 (5,127), 2 (29), 3 (2), 5 (1), or 0 (1,382). Non-zero is
    # music-only in the Classic sample; not visibly promoted by the 2.0.1
    # MHIT loader, so retain as opaque.
    _u32("unk0x1EC", 0x1EC, section_type=_S, min_header_length=0x1F0, default=0),
    _u32("composer_id", 0x1F4, section_type=_S, min_header_length=0x1F8),
    # 0x40 in precisely the 229 media_type=64 records; zero otherwise. It is
    # not visibly promoted by the 2.0.1 MHIT loader.
    _u32("unk0x1F8", 0x1F8, section_type=_S, min_header_length=0x1FC, default=0),
    # Values are 2 (6,199), 0 (341), or 1 (1); opaque format/source marker.
    _u32("unk0x20C", 0x20C, section_type=_S, min_header_length=0x210, default=0),
    # Sparse opaque flags in the Classic 6.5G snapshot: 1 in 25 and 445
    # records respectively. They lie beyond the firmware parser's 0x208 read.
    _u8("unk0x229", 0x229, section_type=_S, min_header_length=0x22A, default=0),
    _u8("unk0x22B", 0x22B, section_type=_S, min_header_length=0x22C, default=0),
]
