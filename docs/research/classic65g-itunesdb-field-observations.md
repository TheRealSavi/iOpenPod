# iPod Classic 6.5G iTunesDB Field Observations

> **Status:** empirical notes, not field-name confirmations.
> **Last updated:** 2026-08-04
> **Scope:** the iPod Classic 6.5G snapshot currently under investigation.

This is the running evidence log for observations made while pairing the
iTunesDB byte walk with a decrypted Classic firmware image.  Each new finding
should also be summarized beside the relevant `FieldDef` entry in
`src/iopenpod/itunesdb_shared/`. A correlation is deliberately kept separate
from a confirmed format meaning.

## Sample and method

The database sample is `/Users/john/Downloads/iTunesDB`:

| Property | Value |
| --- | --- |
| Device | iPod Classic 6.5G / 120 GB (MB565) |
| Firmware | 2.0.1 (33.2.0.1) |
| File size | 20,138,994 bytes |
| SHA-256 | `c242701f0da0893b61d9d9605d6c3782d61d983fac759a6d400df23be732ef8b` |
| Parsed `mhit` records | 6,541 |

Values were read from each `mhit` header by offset and compared across the
whole sample.  This establishes patterns within this one library only; it
does not prove a field's meaning, format contract, or firmware behavior on a
different iPod/database.

## Current MHIT evidence

| Offset | Parser field | Observation | Working interpretation |
| --- | --- | --- | --- |
| `0xB4` | `unk0xB4` | 33 non-zero values; every one exactly equals `bookmark_time` at `0x6C`. All 33 also have `remember_position = 1`. | Likely a bookmark-time compatibility mirror/shadow. Keep raw name until data flow or a controlled edit proves it. |
| `0xC4` | `unk0xC4` | Non-zero for 5,864 records and zero for 677; that is an exact match with `lyrics_flag` at `0xB0`. The non-zero values have 5,647 distinct values. | Opaque lyric-associated identifier or reference, not a Boolean lyric flag. |
| `0xEC` | `unk0xEC` | Non-zero for 3,239 records, all `media_type = 1` (music). 3,230 of those also have non-zero `store_content_flag`. | Store-associated opaque integer. The exact Store role is unknown. |
| `0xF4` | `store_content_flag` | Non-zero for 5,978 records; 34 distinct non-zero values rather than a simple `0`/`1` pattern. | The inherited name may be broadly right, but the value appears packed or enumerated rather than Boolean. |
| `0x100` | `gapless_track_flag` | Every one of the 6,541 records contains `1`. | This database cannot show whether it controls gapless playback; it is not useful as a per-track discriminator in this sample. |
| `0x168` | `unk0x168` | `32` occurs 5,820 times and `1` occurs 721 times. Both occur across several media types. | Candidate feature, source, or provenance value. It is not yet identified. |

### Related distributions

- `gapless_audio_payload_size` (`0xF8`), `unk0xFC` (`0xFC`), `unk0x118`,
  `unk0x11C`, and `unk0x130` were zero in every record of this sample.
- `visible` is `1` and `checked_flag` is `0` in every record. Neither is a
  useful track-level discriminator in this library.
- `not_played_flag = 2` occurs in 1,231 records; 1,220 have both
  `play_count_1 = 0` and no `last_played` timestamp. The eleven exceptions
  have play history, so value 2 is a strong unplayed-state candidate rather
  than a confirmed invariant. Value 1 is the complementary, usually-played
  state in this snapshot.
- `audio_format_flag = 0x0080` is an exact indicator of the 275
  `movie_flag = 1` records; all other tracks use `0xFFFF`. `mp3_flag` exactly
  matches `use_podcast_now_playing_flag`: both are set only on 66 MP3 podcast
  records.
- `gapless_album_flag` (`0x102`) is `1` in 253 records; unlike `0x100`, it
  varies and is a better candidate for targeted differential testing.
- `unk0xB3` is zero in every record.
- `unk0x168` by media type: music (`1`) has 5,457 values of `32` and 716 of
  `1`; the other media types are mostly `32` as well.  Therefore it is not a
  clean audio/video/podcast classifier.
- Every `sort_mhod_indicators` bit 0 exactly matches the presence of its
  respective sort MHOD in this database: types 27, 28, 23, 29, 30, and 31
  occur in 2,518, 6,240, 435, 354, 4, and 41 tracks respectively. Bytes 6 and
  7 are zero everywhere.

### MHIT extended-header evidence

All 6,541 MHIT headers are 0x248 bytes, not the writer's current 0x270-byte
default. The Classic firmware's MHIT loader (`0x0807EA14`) reads the first
0x208 bytes and then skips the header remainder according to its declared
length. That makes the following extension data important to preserve even
when its runtime use is not yet traced.

| Offset | Parser field | Observation |
| --- | --- | --- |
| `0x154` / `0x1A0` | `unk0x154` / `unk0x1A0` | Exact duplicates in all records, non-zero in exactly the 6,108 `purchased_aac_flag = 1` records. There are 508 distinct values. |
| `0x164` | `unk0x164` | Non-zero in 64 records, all purchased music with artwork. Values are unique within those 64 records and do not equal an aligned 32-bit word of `hash_0x104`. It may be part of an extended artwork reference, but no direct relationship has been proven. |
| `0x173` | `unk0x173` | `1` in 180 records, otherwise zero. Static tracing of `0x0807EA14` shows a non-zero value directly sets runtime track bit `0x1000`; this is the only newly catalogued offset in the loader's initial 0x208-byte read with a direct promotion found so far. |
| `0x194` / `0x195` | `movie_flag_2` / `purchased_aac_flag_2` | Exact mirrors of `movie_flag` and `purchased_aac_flag` respectively, across all 6,541 records. |
| `0x197` | `unk0x197` | Values are 1 (6,086), 10 (228), 9 (23), or 0 (204). It tracks broad media families, but does not equal `media_type`. |
| `0x1B0`–`0x1DF` | widened Store block | Six 64-bit values have low 32 bits exactly equal to `store_track_id`, `store_encoder_version`, `store_artist_id`, `unk0xEC`, `store_album_id`, and `store_content_flag`. Only the upper words of the track and album IDs vary: 1 in 130 and 107 records respectively; all other upper words are zero. |
| `0x1EC` | `unk0x1EC` | Values: 1 in 5,127 records, 2 in 29, 3 in 2, 5 in 1, and 0 in 1,382. Every non-zero value is `media_type = 1`, but 1,014 music tracks contain zero. |
| `0x1F8` | `unk0x1F8` | `0x40` in precisely the 229 `media_type = 64` records and zero in every other record. |
| `0x20C` | `unk0x20C` | Values: 2 in 6,199 records, 0 in 341, and 1 in one. Zero covers every `media_type` 2, 4, 32, and 64 record; value 2 covers all 6,173 music records plus 26 of 27 `media_type = 8` records; the sole value 1 record is the remaining audiobook. |
| `0x229` / `0x22B` | `unk0x229` / `unk0x22B` | Sparse flags: 1 in 25 and 445 records respectively. All flagged records are purchased music in this sample; neither flag is a clean genre, album, or artist classifier. Both lie after the loader's initial 0x208-byte read. |

The widened Store block is a preservation finding: its layout is clear, but
the reason Apple duplicated/widened these identifiers remains unknown.

### Header-coverage audit

After adding the MHIA rating and season fields, a complete walk of this
database's 185,016 parsed chunks found no remaining non-zero byte in any
chunk header outside the generic 12-byte chunk prefix or a named parser field.
The remaining unmodelled header gaps are zero in this sample. This is a
coverage result for this exact database, not proof that later iTunes versions
will not use those reserved bytes.

## Firmware correlation points

The decrypted RetailOS image is mapped as ARMv5T at base `0x08000000`.
Useful code landmarks from static analysis are:

| Address | Observation |
| --- | --- |
| `0x0804D13C` | Root `mhbd` database loader/parser. |
| `0x0807EA14` | Recognizes `mhlt` and parses each `mhit` header into a runtime track object. |
| `0x08051B34` | High-level `iPod_Control\\iTunes\\iTunesDB` loader reference. |
| `0x08081174` | `iPod_Control/iTunes/iTunesDB.p7b` handling path. |

The `mhit` parser reads the first 0x208 bytes of the header and then skips the
remaining declared bytes. Stack-relative accesses give a stronger result than
an offset-constant search: `+0x173` is read directly and a non-zero value sets
runtime track flag `0x1000`. The semantic name of that runtime bit is still
unknown. The loader does not visibly promote `+0xB4`, `+0xC4`, `+0xEC`,
`+0xF4`, `+0x100`, `+0x168`, `+0x1B0`, or `+0x1F8` while constructing this
runtime track object. This is scoped evidence for this loader, not proof that
those fields are unused elsewhere in RetailOS. A search for an offset constant
alone is noisy because offsets can be loaded indirectly or reused in unrelated
code. The next reliable step is to trace a specific header value through the
constructed runtime object and compare it with a controlled database change.

The same loader confirms that several established fields are live runtime
inputs: `visible` selects one of three object-allocation classes (raw values
1–3); non-zero `mp3_flag` sets runtime bit `0x1`; the low bit of
`compilation_flag` is copied to a runtime flag; `checked_flag` maps to runtime
bit `0x4`; `has_artwork = 1` sets bit `0x40`; `lyrics_flag` maps to bit
`0x10`; and `movie_flag` maps to both a runtime-byte bit and runtime bit
`0x200`. `explicit_flag` is copied to a runtime byte. By contrast,
`audio_format_flag` and `purchased_aac_flag` are not visibly promoted by this
loader. Most importantly for a misleading inherited name, the loader tests
`not_played_flag == 1` (not merely non-zero) before setting runtime bit `0x8`.
That conflicts with the sample's value-2/zero-play correlation, so neither
mapping should be elevated to a semantic confirmation yet.

## MHOD shared-header and playlist-body evidence

Every one of the 129,496 MHOD common headers has zero in both `unk0x10` and
`unk0x14`. All 80,504 standard string MHOD sub-headers have `unk_0x20 = 1`
and `unk_0x24 = 0`. These are strong preservation defaults in this snapshot,
but not confirmed format-wide constants.

MHOD type 100 has two context-specific layouts. The 47,730 short MHIP-child
bodies contain a `position` value. Within each of the 168 playlists that has
such entries, positions are unique and strictly increasing, so the field is an
ordering key. In 166 of those playlists it equals the parent MHIP `group_id`
for every entry; the other two playlists use a different monotonically
increasing sequence. The field is therefore not a simple zero-based playlist
index, despite that common historical description.

Every one of the 173 MHYP-child MHOD type-102 settings bodies is 332 bytes.
166 are all zero; six share the same four non-zero u32s (`+0x000 = 1`,
`+0x008 = 1`, `+0x04C = 4`, `+0x08C = 120`); and the Music playlist has a
separate pattern. These data identify distinct settings profiles but do not
identify their individual controls.

All 275 MHOD type-32 bodies are 84 bytes and belong exactly to the 275
`movie_flag = 1` tracks (`media_type` 2, 32, or 64). Their `+0x0C` FourCC is
always `avc1`, identifying AVC/H.264 video metadata. The first two u32s form
17 resolution-like pairs, predominantly `(480, 640)`, `(360, 640)`, and
`(468, 640)`. `+0x14` and `+0x18` are identical per record but have 205
distinct values; `+0x2C` clusters around frame-rate-like values such as
23,976, 24,000, 25,000, and 29,970. The remaining field meanings are not
confirmed, so type 32 remains an opaque raw body in the parser.

## Playlist, album, and root-header evidence

### MHYP playlist headers

All 173 `mhyp` records have a 0xB8-byte header.  The loader at `0x0807DD8C`
reads the first 0x6C bytes of each header and creates a runtime playlist.

| Offset | Parser field | Observation | Firmware correlation / interpretation |
| --- | --- | --- | --- |
| `0x2A` | `podcast_flag` | `0` in 159 rows, `0x0100` in 12, and `1` in 2. | In this loader, only bit 0 is copied to the runtime playlist flag. `0x0100` therefore has a different role here or is interpreted elsewhere. |
| `0x30` | `unk0x30_playlist_ref` | Non-zero in 146 rows, with six distinct 64-bit values. Every value exactly equals the `playlist_id` of another MHYP row; each target has `podcast_flag = 0x0100`. | The loader passes this 64-bit pair to `FUN_08039F70`, so it is live parser input. It is an opaque playlist-reference candidate, plausibly a podcast hierarchy link. |
| `0x38` | `unk0x38` | Zero in all 173 headers. | No meaning inferred. |
| `0x3C` | `db_id_2` | One non-zero 64-bit value occurs in 166 rows; seven rows contain zero. | The parsed field is retained; no additional semantic inference from this sample. |
| `0x44` | `playlist_id_2` | Equals the row's primary `playlist_id` in 166 rows; the remaining seven rows are zero. | Strong mirror relationship within this sample. |
| `0x4C` | `unk0x4C` | Zero in all 173 headers. | No meaning inferred. |
| `0x50` / `0x52` | `mhsd5_type` / `phase_game_flag` | `mhsd5_type` is non-zero only once each for 2, 3, 4, 5, and 7, and those rows are the built-in Movies, TV Shows, Music, Books, and Rentals playlists respectively. It equals `phase_game_flag` on those five rows. `phase_game_flag` otherwise is `0x0100` (88), `0x010B` (2), `0x0019` (2), or zero (76). | `mhsd5_type` has a strong built-in content-category relationship in this sample. `phase_game_flag` is a historical, provisional name—not evidence that all non-zero values concern games or that it normally mirrors `mhsd5_type`. |
| `0x54` | `mhsd5_special_flag` | Zero in 124 rows, `0x01000000` in 48, and `1` in one. | Treat as an opaque u32; the 0x01000000 representation is especially important to preserve verbatim. |

The 146 `+0x30` references lead to only six target rows.  Those targets are
all playlist rows with `podcast_flag = 0x0100`; this is a structural
relationship, not just a correlation with track media type.

Static tracing of the same loader adds the following data flow: `master_flag`
selects a separate construction branch, `flag1` low bit becomes a runtime
playlist bit, `flag3` low bit becomes runtime bit `0x4`, and `podcast_flag`
low bit becomes runtime bit `0x10`. `sort_order` is converted by a helper
before being stored in the runtime playlist, while the otherwise-zero
`unk0x38` is copied directly to runtime offset `+0x1C0`. `flag2` and the
header fields after `+0x38` were not visibly promoted by this loader. This is
loader-local evidence, not a claim that those bytes are globally unused.

### MHIP playlist-item headers

All 47,736 `mhip` records have a 0x4C-byte header.

| Offset | Parser field | Observation | Firmware correlation / interpretation |
| --- | --- | --- | --- |
| `0x10` | `podcast_group_flag` | Six rows contain `0x0100`; every one has `track_id = 0`. | The high byte selects the special group-header path in `0x0807DD8C`, confirming this is active parser input. |
| `0x12` | `unk0x12` | The same six group headers contain `0x8000` five times and `0x8001` once; every other row is zero. | The loader does not visibly copy these two bytes into its runtime item, so retain as opaque. |
| `0x24` | `unk0x24_group_persistent_id` | Non-zero only on those same six group headers, with six distinct 64-bit values. None matches an MHIT `db_track_id` or `db_track_id_2` in this sample. | Likely group-level persistent identity or external reference, but unconfirmed. |
| `0x34` through `0x4B` | unmodelled tail | Zero in all 47,736 headers. | Padding or a version-reserved tail in this snapshot. |

### MHIA album headers

The 1,059 `album_id` values map one-for-one to the track library's album IDs.
`platform_flag` has a stronger relationship than its inherited name suggests:
`3` occurs in all six podcast-only albums, `4` in all 14 TV-show-only albums,
and `0x0102` in all 18 compilation-music albums. The remaining 1,021 albums
carry `2` and cover ordinary music plus the sample's movies, music videos, and
audiobooks. This is sample evidence for a content-class/provenance role, not a
universal enumeration.

`album_compilation_flag` is zero in all 1,059 records, including every
`platform_flag = 0x0102` album; it is therefore not the compilation signal in
this database. Conversely, every non-zero `album_track_db_id` (all 1,059) is
exactly one member track's `db_track_id`, confirming that it is a
representative-member reference in this sample.

Previously unmodelled MHIA bytes also carry non-zero data. `+0x28` uses the
standard 0–100 rating scale in 454 albums; `+0x29` is exactly `0x20` for
those rated albums and zero otherwise. The `+0x28` value equals the maximum
member-track rating in 391 of the 454 rated albums, which supports an
album-rating interpretation but does not yet establish the aggregation rule.
At `+0x2C`, 13 non-zero values occur only in TV-show albums; each is exactly
the common MHIT `season_number` of every member track. The parser now exposes
that as the album-level `season_number` mirror and retains the rating bytes.

### MHBD root-header singleton values

This one database has `unk0x22 = 611`, `unk0x50 = 111`, `unk0x54 = 255`,
`unk0xA4 = 25`, and `unk0xA6 = 10`. These are single observations—not
inferences—and are recorded in the field definitions so a future sample can
compare them directly.

The header is `0xF4` bytes with `hashing_scheme = 1`. Its `hash58` (20-byte)
and `hash72` (46-byte) regions are both fully populated, while `unk0x32` and
the 57-byte `hashab` region at `0xAB` are all zero. This confirms that a
Classic iTunesDB can retain a HASH72-shaped signature beside its active
HASH58 scheme; it does **not** show that Classic firmware selects HASH72 for
validation.

## Rules for future changes

1. Preserve the raw field and its offset unless direct data flow or a
   controlled differential test confirms a semantic rename.
2. Record the sample, record count, and exact correlation before adding a
   parser comment.
3. Mark correlations as observations, not facts.  The firmware can still use
   a field in a context not exercised by this library.
4. Test mutations on a copy or virtual iPod first.  No real-device database
   writes were made to obtain the observations above.
