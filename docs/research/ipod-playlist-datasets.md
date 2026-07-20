# iPod Playlist Datasets

This document is the working reference for iOpenPod's iTunesDB playlist model.
It is based on libgpod's reader/writer behavior, the iPodLinux iTunesDB wiki,
and iOpenPod's parser/writer code.

The main trap: a playlist row is not self-describing enough. The same `mhyp`
fields have different meaning depending on the parent `mhsd` dataset. In
particular, `mhyp.master_flag == 1` means "library/master playlist" in dataset
2/3, but it can also appear on dataset-5 firmware category playlists such as
Music, Movies, and Rentals.

## Primary Sources

- libgpod `itdb_itunesdb.c`: `get_playlist()`, `write_playlist()`,
  `write_mhsd_playlists()`, `itdb_write_file_internal()`.
  Source: <https://raw.githubusercontent.com/fadingred/libgpod/master/src/itdb_itunesdb.c>
- libgpod `itdb_playlist.c`: `itdb_playlist_is_mpl()`,
  `itdb_playlist_set_mpl()`, `itdb_playlist_is_podcasts()`,
  `itdb_playlist_set_podcasts()`.
  Source: <https://raw.githubusercontent.com/fadingred/libgpod/master/src/itdb_playlist.c>
- libgpod `itdb_private.h`: `ItdbPlFlag` and
  `Itdb_Playlist_Mhsd5_Type`.
  Source: <https://raw.githubusercontent.com/fadingred/libgpod/master/src/itdb_private.h>
- iPodLinux iTunesDB wiki: chunk structure, playlist fields, podcast grouping,
  smart playlist MHODs, and library index MHODs.
  Source: <http://www.ipodlinux.org/ITunesDB>

## Top-Level Dataset Model

The iTunesDB top-level chunk is `mhbd`. Its children are `mhsd` datasets. An
`mhsd` is a typed container; the type at offset `+0x0C` decides which child list
is inside.

| MHSD type | Child | Purpose | iOpenPod bucket |
| --- | --- | --- | --- |
| `1` | `mhlt` | Track list. Contains every `mhit` track row. | `mhlt` / `tracks` |
| `2` | `mhlp` | MHSD type 2 playlist list. Contains library master and user playlists. | `mhlp` / `playlists` |
| `3` | `mhlp` | MHSD type 3 playlist list. Similar to type 2, but podcast-flag playlist entries can use grouped `mhip` rows. | `mhlp_podcast` / `dataset3_podcast_playlists` |
| `4` | `mhla` | Album list. | `mhla` |
| `5` | `mhlp` | Firmware smart/category playlist list. Built-in browse categories live here. | `mhlp_smart` / `smart_playlists` |
| `6` | `mhlt` | Empty stub in libgpod-style writes. | generated stub |
| `8` | `mhli` | Artist list. | `mhsd_type_8` |
| `9` | raw bytes | Genius CUID dataset when present. | preserved blob |
| `10` | `mhlt` | Empty stub in libgpod-style writes. | generated stub |

libgpod writes type `1`, then `3`, then `2`, then `4`, `8`, `6`, `10`, then
`5`, with type `9` included when a Genius CUID exists. iOpenPod tries to
preserve original dataset ordering where possible, but the important rule is
that type `3` must appear before type `2` when podcast support is enabled.

## Core Playlist Chunks

`mhlp` is only a playlist-list wrapper. It has a count and a sequence of `mhyp`
children.

`mhyp` is a playlist row:

| Offset | Field | Meaning |
| --- | --- | --- |
| `+0x0C` | `mhod_child_count` | Number of playlist metadata objects. |
| `+0x10` | `mhip_child_count` | Number of playlist item rows. |
| `+0x14` | `master_flag` / `type` | Dataset-sensitive. Master in type 2/3, category marker in type 5. |
| `+0x15..17` | `flag1..3` | Extra flags, mostly preserved/unknown. |
| `+0x18` | `timestamp` | Playlist creation timestamp, Mac epoch. |
| `+0x1C` | `playlist_id` | 64-bit persistent playlist ID. |
| `+0x28` | `string_mhod_child_count` | Usually `1` for title string. |
| `+0x2A` | `podcast_flag` | `0` normal, `1` Podcasts playlist. |
| `+0x2C` | `sort_order` | Firmware display sort for this playlist's `mhip` order. |
| `+0x3C` | `db_id_2` | Database-wide ID reference for non-master rows. |
| `+0x44` | `playlist_id_2` | Playlist ID mirror for non-master rows. |
| `+0x50` | `mhsd5_type` | Dataset-5 category type. |
| `+0x52` | `mhsd5_type_2` | Usually mirrors `+0x50`. |
| `+0x54` | `mhsd5_special_flag` | Special value for Ringtones/Movie Rentals in libgpod. |
| `+0x58` | `timestamp_2` | Timestamp mirror. |

`mhip` is a playlist item row. For normal playlists it references a track ID.
For dataset-3 podcast grouping, some `mhip` rows are group headers with no track
ID.

## Dataset 2: MHSD Type 2 Playlists

Dataset 2 is the normal playlist universe. It contains:

- Exactly one master/library playlist as the first `mhyp`.
- Zero or more user-created manual playlists.
- User-visible smart playlists, when we decide to keep them visible under
  Playlists.

Rules:

- The master playlist must be first.
- Generated output writes exactly one master playlist with `master_flag == 1`.
- Parsed non-master rows are not moved just because a flag looks surprising;
  malformed or ambiguous master rows should fail visibly instead of being
  guessed into shape.
- The master playlist name is the iPod display name used by iTunes-style UIs.
- The master playlist should contain all playable tracks that belong in the
  library. libgpod specifically notes that podcasts may not be represented in
  the master playlist the same way normal music is.
- The master playlist is the only dataset-2 playlist that should get library
  index MHODs `52` and `53`.

iPodLinux documents the first playlist as the Library playlist and says it has
the hidden/master bit set and contains all songs. libgpod enforces the same
model by treating the first playlist as the master and warning that callers must
not move it.

## Dataset 3: MHSD Type 3 Playlists

Dataset 3 is another `mhlp`. It is not just "the podcast playlist"; it can hold
ordinary playlist rows too. Its special behavior is that rows marked with
`podcast_flag == 1` can use grouped `mhip` entries for show/episode structure.

Rules:

- It should contain the same master playlist shape as dataset 2.
- It should contain the Podcasts playlist with `podcast_flag == 1`.
- The Podcasts playlist title is not the controlling field; `podcast_flag` is.
- Only one playlist should have `podcast_flag == 1`.
- For the podcast playlist in dataset 3, entries are grouped by show/album.

Podcast grouping:

- Group header `mhip`: `podcast_group_flag == 256`, `track_id == 0`,
  `group_id` set to a synthetic unique ID, child `mhod` type `1` with the show
  name.
- Episode `mhip`: `podcast_group_flag == 0`, real `track_id`, its own
  `group_id`, and `podcast_group_ref` pointing to the header `group_id`.
- Normal non-podcast playlists in dataset 3 use ordinary flat `mhip` entries.

UI policy:

- Render dataset-3 group headers as parsed structure so we can inspect the
  firmware's podcast/show grouping.
- Do not present those headers as general editable playlist folders. They are
  `mhip` item groups inside a podcast playlist, not playlist containers.
- Preserve any group title MHOD attached to a group-header `mhip`; it is part
  of the dataset-3 evidence.

Older compatibility code sometimes treated dataset 3 as a fallback/clone of
dataset 2 because libgpod can read one preferentially over the other. iOpenPod's
current storage rule is stricter: dataset 2 and dataset 3 are separate playlist
universes, and equal `playlist_id` values across them are not collapsed in the
raw cache or writer. The final UI projection may display same-ID type 2/type 3
twins as one visible playlist, but that row must explicitly show that it
represents both MHSD type 2 and MHSD type 3 origins. The writer only clones
dataset 2 into dataset 3 for new/default writes where no explicit dataset-3
list exists.

## Playlist Folders

Modern iTunes/Music libraries have playlist folders, but this audit has not
found a libgpod/iPodLinux-backed iPod `mhsd`/`mhyp` folder model equivalent to
the dataset-3 podcast grouping above. The known on-device grouping mechanism we
can prove today is item-level `mhip` grouping inside the dataset-3 Podcasts
playlist.

Policy until we have device samples:

- Do not encode playlist folders by reusing dataset-3 podcast group headers.
- Do not infer folders from duplicate playlist IDs, titles, or sort order.
- If a future sample shows real on-device playlist folder metadata, preserve
  its parent dataset and raw fields first, then add a separate writer path.

## Dataset 5: Firmware Category / Smart Playlist List

Dataset 5 is the confusing one. It is an `mhlp` containing `mhyp` rows, but it is
not the same universe as dataset 2.

libgpod stores dataset-5 playlists separately (`itdb->priv->mhsd5_playlists`).
When reading, `get_playlist()` routes `mhsd_type == 5` rows into that list
instead of the normal `itdb->playlists` list. When writing, `write_mhsd_playlists()`
chooses `mhsd5_playlists` only for type `5`; types `2` and `3` use the normal
playlist list.

Known `mhsd5_type` values from libgpod:

| Value | Meaning |
| --- | --- |
| `0` | None / not a firmware category |
| `2` | Movies |
| `3` | TV Shows |
| `4` | Music |
| `5` | Audiobooks |
| `6` | Ringtones |
| `7` | Movie Rentals / Rentals |

Rules:

- A non-zero `mhsd5_type` means dataset-5 firmware category, not user playlist.
- Dataset-5 categories can legitimately have `master_flag == 1`.
- That `master_flag` must not be interpreted as the dataset-2 master playlist.
- Dataset-5 rows normally have smart playlist prefs/rules (`mhod` 50/51) that
  define their category filter.
- libgpod writes zero `mhip` rows for generated dataset-5 playlists even when
  the smart rule would match tracks. When parsing an existing iPod, preserve
  any dataset-5 `mhip` rows and per-item metadata exactly enough to round-trip.
- Ringtones and Movie Rentals have extra special handling in the extended MHYP
  area. libgpod writes `1` in that special field, and iOpenPod now follows
  that public mirror. Older iOpenPod comments used `0x200`, so this still needs
  Apple iTunes/Finder sample comparison.

Practical consequence: never derive the iPod name, backup display name, or
dataset-2 master playlist from a row with `_source == "category"` or
`mhsd5_type != 0`. This is the source of the `Rentals`-renaming failure class.

## Smart Playlists

Smart playlists are represented by playlist-level MHODs:

- `mhod` type `50`: smart playlist preferences (`SPLPref`), including live
  update, rule enable, limit enable, limit type/sort/value, and checked-only
  behavior.
- `mhod` type `51`: smart playlist rules (`SLst`). Rule payloads switch to
  big-endian structures after the rule-list marker.
- Optional `mhod` type `102`: playlist settings blob.

User-visible smart playlists can live in dataset 2 if we want them under
Playlists. Dataset-5 built-in categories are also smart-ish rows, but should
stay in dataset 5 when `mhsd5_type != 0`.

iOpenPod policy:

- Dataset-5 row with `mhsd5_type == 0` and smart prefs/rules: keep it in
  dataset 5. Dataset origin is authoritative; do not silently migrate between
  datasets.
- Dataset-5 row with `mhsd5_type != 0`: keep in dataset 5, preserve parsed
  membership, and do not synthesize `master_flag` from `mhsd5_type`.
- Dataset-2/3 row with `_source == "category"` or `mhsd5_type != 0`: preserve
  the row in its parent dataset. That combination is suspicious enough to
  surface in audit/UI state, but it is not permission to relocate the row.

## Library Index MHODs 52/53

The master/library playlist can carry fast-browse indexes:

- `mhod` type `52`: sorted index of master playlist entries.
- `mhod` type `53`: jump table for fast scrolling.

iPodLinux describes these as indexes for the Browse menu. libgpod writes
title, artist, album, genre, and composer index/jump-table pairs when the
master playlist has members.

Rules:

- Write them only on the dataset-2/3 master playlist.
- Do not write them on user playlists.
- Do not write them on dataset-5 category rows, even if those rows have
  `master_flag == 1`.

## Flags That Are Commonly Confused

| Field | Correct interpretation |
| --- | --- |
| `mhyp.master_flag` | Dataset 2/3: exactly one master/library playlist. Dataset 5: category marker may be set on several rows. |
| `mhyp.podcast_flag` | Playlist-level Podcasts UI marker. It controls Podcasts playlist behavior more than the title does. |
| `mhit.podcast_flag` / now-playing flag | Track-level podcast presentation behavior. Not the same as playlist `podcast_flag`. |
| `mhit.media_type` | Track media classification used by smart rules and firmware browse categories. |
| `_source` | iOpenPod UI/cache classification, not on-disk. Must be recomputed from dataset and `mhsd5_type`. |
| `mhsd5_type` | Dataset-5 category type. Non-zero means firmware category, not visible user playlist. |

## iOpenPod Implementation Map

Parser:

- `iopenpod.itunesdb_parser.mhsd_parser.parse_dataset()` reads the `mhsd_type`.
- `iopenpod.itunesdb_parser.chunk_parser._parse_child_list()` parses `mhlp` as a generic
  list container.
- `iopenpod.itunesdb_parser.mhyp_parser.parse_playlist()` reads `mhyp` fields via
  `iopenpod.itunesdb_shared.mhyp_defs`.
- `iopenpod.sync._db_io.read_existing_database()` normalizes parsed datasets into
  `tracks`, `dataset2_standard_playlists`, `dataset3_podcast_playlists`, and
  `dataset5_smart_playlists`.
- `iopenpod.application.runtime.iTunesDBCache.get_playlists()` presents all playlist
  buckets for UI and stamps `_source` plus `_mhsd_dataset_type` without
  deduplicating equal playlist IDs across datasets.

Writer:

- `iopenpod.itunesdb_writer.mhbd_writer.write_mhbd()` assembles dataset chunks and
  decides ordering.
- `iopenpod.itunesdb_writer.mhlp_writer.write_mhlp_with_playlists()` generates dataset-2
  master + user playlists.
- `iopenpod.itunesdb_writer.mhlp_writer.write_mhlp_with_playlists_type3()` generates the
  podcast-special dataset from explicit dataset-3 input, or from dataset 2 only
  when no explicit dataset-3 input is supplied.
- `iopenpod.itunesdb_writer.mhlp_writer.write_mhlp_smart()` writes dataset-5 categories.
- `iopenpod.itunesdb_writer.mhyp_writer.write_mhyp()` writes the shared playlist row,
  including dataset-5 extended fields.
- `iopenpod.sync._playlist_builder.build_and_evaluate_playlists()` is the policy
  boundary that builds dataset 2, 3, and 5 outputs separately.

## Hard Invariants

- Generated dataset 2 and dataset 3 each get an auto-written master playlist at
  the start of the list.
- Existing playlist rows are not moved between datasets based on flags that look
  surprising. Parent MHSD origin is part of the playlist identity.
- Equal playlist IDs in different MHSD datasets are distinct rows. UI selection,
  deletion, and cache replacement must include dataset origin when known.
- Dataset 5 rows must not be used to infer the device name.
- Dataset 5 categories may carry `master_flag`; do not sanitize this away for UI
  or write prep.
- Do not synthesize dataset-5 `master_flag` from `mhsd5_type`. Preserve the
  parsed byte and let samples teach us which devices set it.
- Dataset 3 must be written before dataset 2 when included.
- Podcast grouping belongs only to dataset 3's Podcasts playlist.
- `mhip` ordering is the display order. If we sort, we must also regenerate or
  clear positional item metadata.
- Smart playlist live-update evaluation is an application policy. Dataset-5
  categories should preserve their category identity even if we also compute
  matched track IDs internally.

## Current Risk Areas

- iPod 5.5G sample at `/Users/john/Desktop/ipod5.5`:
  - Database version `117`, dataset order `[4, 1, 3, 2, 5, 9]`.
  - Dataset 2 and dataset 3 contain the same six playlist titles and IDs:
    `John Gibbons's iPod`, `Every Rule`, `Horchata`, `La Concha`,
    `Mucha Gracias`, and `My M Playlist`.
  - `Every Rule` is a smart playlist in both dataset 2 and dataset 3 with
    `rule_count == 47`, `conjunction == 0` (`AND`), and SLst `unk004 ==
    0x00010001`.
  - Dataset 5 contains `Audiobooks`, `Movies`, `Music`, `TV Shows`, and
    `Videos`; all are smart/category rows.
  - MHSD type 9 is present as raw Genius CUID payload
    `41bac68ce330182aeedfdc61bdb677e8`.
  - New SPL field IDs observed in `Every Rule` but not named by libgpod's
    public enum: `0x1D` Checked, `0x25` Album Artwork, `0x59` Video Rating,
    `0x85` Location, `0x86` Cloud Status, `0x9A` Favorite / Suggest Less,
    `0x9C` Album Favorite / Suggest Less, `0x9F` Work, `0xA0` Movement Name,
    and `0xA1` Movement Number.
  - The labels above come from the rule entry order in the sample. The rules
    were entered alphabetically in iTunes; the binary preserves that order.
  - String-like rules in this sample use only the iTunes string action family:
    Contains, Does not contain, Is, Is not, Begins with, and Ends with. The
    observed string fields are Album, Album Artist, Artist, Category, Comments,
    Composer, Description, Genre, Grouping, Kind, Movement Name, Sort Album,
    Sort Album Artist, Sort Artist, Sort Composer, Sort Show, Sort Title, Title,
    Video Rating, and Work. iOpenPod still keeps legacy/libgpod string support
    for `0x3E` TV Show, even though that field was not present in this 47-rule
    iPod 5.5G sample.
  - Boolean rules use only `is true` and `is false`. The observed/known boolean
    field family is exclusively Album Artwork, Checked, Compilation, and
    Purchased; do not coerce other one-byte-looking fields into booleans without
    a device sample proving that rule type.
  - Some non-string, non-boolean fields are finite-choice menus: Album Favorite
    / Suggest Less, Cloud Status, Favorite / Suggest Less, Location, Media Kind,
    and Playlist. Their UI actions are `is` / `is not`, followed by a constrained
    value set. The 5.5G sample proves this shape and proves several raw values
    (`2` for the default favorite/cloud-status samples, `1` for Location on this
    computer, `1` for Media Kind Music), but not every raw value in every menu.
    iOpenPod keeps unknown parsed values as raw values and does not invent raw
    values for unresolved entries such as Media Kind: Home Video.
  - Integer comparison fields use `is`, `is not`, `is greater than`, `is less
    than`, and `is in the range`: Album Rating, Bit Rate, BPM, Disc Number,
    Movement Number, Plays, Rating, Sample Rate, Size, Skips, Time, Track
    Number, and Year. Ratings are displayed in stars but stored as the iPod raw
    rating scale; Size is displayed in MB but stored in bytes.
  - Date fields use absolute comparisons (`is`, `is not`, `is after`, `is
    before`, `is in the range`) plus relative comparisons (`is in the last`,
    `is not in the last`) with days/weeks/months. The date fields are Date
    Added, Date Modified, Last Played, and Last Skipped. Absolute SPL date
    values in the 5.5G sample are Mac-epoch timestamps; relative rules use
    signed `from_date` counts plus unit seconds.
- `mhsd5_special_flag` for Ringtones/Rentals differs between libgpod mirror
  behavior and old iOpenPod comments. The writer follows libgpod (`1`) today;
  we need samples from Apple iTunes/Finder for Nano 7 and Classic to settle it.
- Dataset 2 versus dataset 3 is now explicit in code. iOpenPod keeps both raw
  buckets separate through read, UI cache, quick writes, sync prep, and binary
  write. The writer clones dataset 2 into dataset 3 only for new/default writes
  where no explicit dataset-3 list is supplied.
- `_source` stamping is spread across runtime, quick writes, and sync executor.
  The predicate for category detection should eventually be centralized.
- The top-level writer comments mention outdated dataset counts in places.
  Keep comments aligned with generated datasets to avoid future regressions.
- SQLite-era iPods may have additional category/container expectations beyond
  binary iTunesDB. The binary dataset rules are necessary but may not be
  sufficient for Nano 6/7 and Classic late firmware. SQLite containers are a
  separate model; today we do not invent a dataset-3 analogue there without
  device samples.

## Recommended Policy

Use this routing table whenever code touches playlists:

| Input row | Output bucket | Master-name eligible? |
| --- | --- | --- |
| `_mhsd_dataset_type == 2` | Dataset 2 | Dataset-2 master rows only |
| `_mhsd_dataset_type == 3` | Dataset 3 | Dataset-3 master rows only |
| `_mhsd_dataset_type == 5` | Dataset 5 | No |
| New UI/import playlist without origin | Dataset 2 | No |
| Legacy pending row with `_source == "podcast"` | Dataset 3 | No |
| New UI/import playlist with `_source == "category"` | Dataset 5 | No |

When in doubt, preserve the parent dataset and header fields. Do not relocate a
row because its flags look like another dataset's common pattern.
