# Podcast authoring comparison: source expectations and catalog matching

Investigated on **2026-10-18**, with working-tree base
`f5a1a97919c50a552d282072b3be768ed4001626` and Original iOpenPod
`a20242428b93b672d14b37230772dbad75139c69` (`origin/1.x`).

The authoring comparisons are **source-derived expectations and comparison
checks**, not measured results from the new virtual iPod runs. The separate
experiment owns those results. The catalog-matching section below is a measured,
read-only experiment against the four original captures. Artwork, chapters, and
Podcast group references are covered by the
[primary-source report](podcast-primary-sources.md); this note focuses on other
differences. Working-tree source links identify the named functions and line
positions inspected during the experiment.

## Establish what the comparison actually exercises

Podcast Sync constructs a new Track through
[`episode_track()`](../../src/iOpenPod/app/podcasts/media.py#L121), then supplies
that metadata to the media pipeline and `_song()`. It does not reconstruct all
Apple MHIT fields from a downloaded media file. Re-adding a complete Apple-derived
semantic Track through ordinary Host Sync is therefore a different experiment
from Podcast Sync using recovered feed/episode metadata.
[`_prepare_podcasts()` call site](../../src/iOpenPod/app/sync_execution.py#L1535),
[`_song()`](../../src/iOpenPod/app/sync_execution.py#L2043).

Record the chosen route, seed database provenance, input metadata, transcoding
options, and whether the media bytes changed. Match episodes across outputs by
enclosure URL/GUID plus corroborating title/date, not newly allocated Track IDs,
filenames, or database offsets. Fresh native identities are allocated without
renumbering surviving source records.
[`IdentityAllocator`](../../src/iPodDB/library/_identities.py#L6).

## Measured: feed refresh loses correspondence with Apple Episodes

On 2026-10-18, the real `IPodLibrary`, `reconcile_device_podcasts()`,
`merge_fetched_subscription()`, and `plan_podcast_sync()` were exercised against
each unchanged Apple capture and the 15 corresponding publisher Episodes saved
by the parent investigation. Planning explicitly selected all 15 fetched Episodes
with `automatic=False`. No downloads or device/database writes were executed.
Private evidence includes source/input SHA-256 values, per-model counts, and the
15 episode comparisons in
`.scratch/podcast-virtual-comparison/catalog-matching.json`.
The publisher input is
`.scratch/podcast-virtual-comparison/publisher-inputs.json`.
These ignored files remain local research artifacts.

Every model produced the same measured result:

| Stage | Subscriptions | Catalog Episodes | On device | Off device |
| --- | --- | --- | --- | --- |
| Recover from original database | 3 | 15 | 15 | 0 |
| Merge the 15 fetched Episodes | 3 | 30 | 15 | 15 |
| Reconcile against the same original database again | 3 | 30 | 15 | 15 |

Both plans, immediately after merge and after the second reconciliation, scheduled
**15 additions, zero removals, and zero issues**. All 15 planned additions had an
existing native Track with the same show/title: six Joe Rogan Experience, five
Murder With My Husband, and four Buzzcast Episodes. This proves that current
catalog matching and the duplicate guard permit repeat additions for these
captures; it does not claim those additions were executed.

The raw value exposed as `podcast_enclosure_url` (MHOD 15) was non-HTTP text on
all 15 Tracks in all four captures. Ten values exactly matched the corresponding
current feed GUID. Five Murder With My Husband values differed from their current
feed GUID despite matching titles. Every native `Track.episode` (MHOD 20) was
empty. Thus the historical field name does not justify treating every MHOD 15
value as a download URL. The ten exact matches provide identity evidence; the
other five require additional corroboration before automatic association.

The measured result follows the current source behavior:

1. [`_episode_from_track()`](../../src/iOpenPod/app/podcasts/catalog.py#L436)
   copies MHOD 15 into `enclosure_url` but reads `guid` only from `Track.episode`.
   [`episode_identity()`](../../src/iOpenPod/app/podcasts/identity.py#L53)
   prioritizes any nonempty normalized enclosure, and
   [`normalize_media_url()`](../../src/iOpenPod/app/podcasts/identity.py#L81)
   preserves opaque strings. The recovered token and fetched HTTP media URL
   consequently generate different enclosure identities.
2. [`merge_fetched_subscription()`](../../src/iOpenPod/app/podcasts/catalog.py#L182)
   matches by episode identity or unique nonempty GUID; it does not compare the
   native enclosure token to the fetched GUID. It retains unmatched on-device
   Episodes, so the feed refresh creates 15 additional catalog entries.
3. [`_ambiguous_identity()`](../../src/iOpenPod/app/podcasts/sync.py#L221)
   checks native textual episode IDs and valid HTTP(S) enclosure URLs. Neither
   includes these native opaque MHOD 15 values, so the explicit additions pass
   through [`plan_podcast_sync()`](../../src/iOpenPod/app/podcasts/sync.py#L55).

This is a compatibility defect candidate in identity interpretation, separate
from byte preservation and fresh authoring. A future fix needs to retain raw
MHOD 15 data while distinguishing media URLs from opaque identities, preserve
existing local Episode/history identities when merging, and reject ambiguous
matches. These observations do not justify overwriting all MHOD 15 fields or
automatically matching the remaining five Episodes by title alone. No runtime
change was made in this experiment.

## Expected differences worth classifying

| Area | Current source expectation | How to interpret a difference |
| --- | --- | --- |
| Classification | `episode_track()` supplies audio Podcast alone: native `0x04`; video Podcast uses the compound video value. [`episode_track`](../../src/iOpenPod/app/podcasts/media.py#L121), [`encode_media_types`](../../src/iPodDB/library/_native_values.py#L46). | Apple's captured `0x05` also sets audio. Compare independent bits and menu behavior; do not label `0x04` a missing Podcast marker. |
| Title/show/artist | Title comes from the episode; album and show from subscription title; artist and album artist from subscription author. [`episode_track`](../../src/iOpenPod/app/podcasts/media.py#L121). | Empty publisher author stays empty. Original fell back to the feed title for artist. |
| Episode details | GUID becomes textual episode ID; episode number becomes both track number and episode number; season gets its own field. Genre is always `Podcast`, with category stored separately. [`episode_track`](../../src/iOpenPod/app/podcasts/media.py#L121). | Original derived genre from category, year from publication time, and disc number from season. Those are input-policy differences, not structural corruption. |
| Unrepresented feed metadata | The current `PodcastEpisode` model has no content-advisory, subtitle, copyright, or episode-author field; the RSS adapter selects plain-text subtitle/summary as description. [`PodcastEpisode`](../../src/iOpenPod/app/podcasts/models.py#L96), [RSS adapter](../../src/iOpenPod/app/podcasts/feed_client.py#L350). | Check whether Apple has useful values here. A missing value may originate before serialization; adding a writer field alone cannot recover it. |
| Playback | New Podcast Tracks request resume, shuffle exclusion, Podcast Now Playing, and explicit listened state. New MHIT defaults mark unplayed as `2`; edits author `1` or `2`. [`episode_track`](../../src/iOpenPod/app/podcasts/media.py#L143), [played-state writer](../../src/iPodDB/library/_track_writing.py#L344). | Compare play count, listened state, bookmark, and last-played independently. A fresh add is not a copy of all Apple playback history. |
| Dates | Sync supplies a new `date_added`; fresh Podcast metadata normally leaves `last_modified` zero. Release date is UTC; other editable MHIT dates use Device Time Context. [`_song`](../../src/iOpenPod/app/sync_execution.py#L2088), [date encoding](../../src/iPodDB/library/_track_writing.py#L305). | Original's writer used `last_modified or date_added`. A time difference must be classified as a new event, absent input, or conversion discrepancy before proposing a fix. |
| Native private metadata | Fresh MHITs start from shared defaults; only mapped semantic and verified media fields are authored. Store IDs, unknown extensions, purchase history, and Apple-private metadata are not reconstructed. [MHIT defaults](../../src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py#L13), [`edit_track`](../../src/iPodDB/library/_track_writing.py#L253). | Raw differences in fresh records are expected; unexplained loss from retained records is a different preservation question. |
| Media facts | Duration, bitrate, file size, sample rate, format, and location come from prepared output; transcoding clears carried gapless timing. [`_song`](../../src/iOpenPod/app/sync_execution.py#L2043), [native codec assignment](../../src/iPodDB/library/_track_writing.py#L518). | Compare against the actual output file. Small duration/bitrate differences can reflect measurement or transcoding, while mismatched file sizes or invalid references need investigation. |

Original comparisons above are directly inspectable in its
[Podcast adapter][original-podcast] and [MHIT writer][original-mhit]. Do not adopt
every historical choice automatically: Original truncates feed description to
255 characters in its adapter, whereas current metadata carries the description
into the shared field-specific writer.

## Model-dependent layout and publication

ADR-0171 subsequently changes Mini 2G and full-size iPod 5G/5.5G to baseline `0x30`
and 624-byte headers, resolving the artist-reference conflict described below.
The following table records the policies at the time of this investigation.

These are Device Registry authoring policies, not claims about maximum
firmware support. Source: [capability definitions](../../src/device_registry/data/catalog.py#L136)
and [model assignments](../../src/device_registry/data/catalog.py#L212).

| Model | Profile database version | Fresh MHIT header | Primary output | Signing |
| --- | --- | --- | --- | --- |
| Classic 6.5 | `0x30` | `0x270` / 624 bytes | iTunesDB | HASH58 |
| Mini 2 | `0x13` | `0x148` / 328 bytes | iTunesDB | None |
| Nano 2 | `0x13` | `0x148` / 328 bytes | iTunesDB | None |
| Nano 5 | `0x30` | `0x270` / 624 bytes | iTunesCDB plus SQLite artifact set | HASH72 for both |

Fresh Track layout is selected from the profile, independently of a retained
MHBD version. When new/grown Tracks require a version update, reconciliation uses
the maximum of retained and selected versions; it does not lower an Apple version
117 root. Thus an Apple-derived empty seed can legitimately retain root version
117 while newly authored Mini/Nano 2 Tracks use 328-byte headers.
[`creation_header_length`](../../src/iPodDB/library/_track_header_expansion.py#L13),
[version selection](../../src/iPodDB/library/_reconcile.py#L156).

There is a seed-sensitive failure to watch: retaining dataset 8 requires changed
artist groups to receive `artist_id_ref`, located at MHIT `0x1E0`, beyond the
328-byte layout. An Apple-derived seed with that dataset can therefore conflict
with fresh Mini/Nano 2 layout policy. Record a preparation rejection if encountered;
do not silently strip the dataset to obtain a passing comparison.
[`derived_header_requirements`](../../src/iPodDB/library/_track_header_requirements.py#L13).

## Playlists, browse structures, and SQLite

A structural edit supplies dataset 2 when only dataset 3 exists, and orders
dataset 3 before dataset 2. Existing counterparts retain their own private data.
New or structurally changed Master Playlists gain missing MHOD 52/53 pairs for
sort types `3`, `5`, `4`, `7`, and `0x12`. Therefore extra standard indexes or a
flat companion can be expected output rather than accidental duplication.
[`ensure_companion`](../../src/iPodDB/library/_playlist_datasets.py#L179),
[`ensure_master_indexes`](../../src/iPodDB/library/_hidden_writing.py#L42).

Album/artist datasets 4/8 are maintained only when already present; the writer
does not fabricate these optional datasets from an empty seed. Category dataset 5
retains independent ownership. Seed selection therefore affects the native output
even for identical incoming episodes. Compare dataset counts, Master membership,
index targets, category membership, and retained unknown records before treating
total file size as a quality metric.
[Browse maintenance](../../src/iPodDB/library/_hidden_writing.py#L192),
[dataset rules](../adr/0024-reconcile-and-verify-playlists-by-dataset.md).

New MHIA album records default `content_type_flag` at `0x1C` to `2`; retained
records keep their existing value. Original called this field `platform_flag`
and authored `2` unconditionally. If Apple supplies
another value for Podcast albums, retain that as a producer difference whose
firmware meaning needs evidence, not an instruction to overwrite source fields.
[MHIA definition](../../src/iPodDB/iTunesDB/shared/chunk_defs/mhia.py#L13),
[album reconciliation](../../src/iPodDB/library/_hidden_writing.py#L295),
[Original MHIA writer][original-albums].

For Nano 5, compare all five SQLite databases plus `Locations.itdb.cbk`, not just
CDB. Current generation preserves native category metadata, independently projects
media bits into flags, and creates `podcast_info` for every Podcast-bit Track.
Consequently `0x04` and `0x05` produce different `is_song` values while both produce
`is_podcast=1`. `podcast_info.external_guid` remains NULL even when the Track has a
textual episode ID; Original also left it NULL. That omission is worth documenting
if Apple populates it, but these sources do not establish it as required.
[Native projection](../../src/iPodDB/library/_sqlite_projection.py#L106),
[media flags](../../src/iPodDB/SQLiteDB/database.py#L246),
[Podcast rows](../../src/iPodDB/SQLiteDB/database.py#L611),
[Original SQLite writer][original-sqlite].

Schema/integrity success does not prove firmware acceptance. Current generation
already follows Original file-header semantics, sequential browse-group IDs,
zero absent-name references, and empty Store rows; it retains deliberate
improvements such as compound media flags and verified native sample counts.
Compare actual schema objects and linked row contents, not serialized page bytes
or surrogate browse IDs. [ADR-0147](../adr/0147-restore-late-ipod-firmware-write-compatibility.md),
[schema](../../src/iPodDB/SQLiteDB/schema.py).

## Virtual setup and signing requirements

`VirtualStoragePlatform.add_volume()` registers an existing ordinary directory;
it does not initialize iPod files or emulate firmware. Its hardware arguments are
`identifiers` and `probe_result`. Use independent device/volume identities for each
model. A seed needs the normal iPod marker and readable database plus sufficient
Device Evidence for selection. No standalone blank-iPod initialization workflow
was found in the inspected application code.
[Virtual adapter](../../src/storage/testing.py#L43),
[selection boundary](../adr/0016-qualify-device-candidates-and-correlate-macos-hardware.md).

Classic HASH58 writes require the device's eight-byte FireWire GUID. Nano 5 HASH72
requires retained signing material: the coordinator tries matching HashInfo,
then the retained database, then a matching Locations database/checksum book.
Unsigned blank files cannot substitute for that evidence. The coordinator builds
the complete `WriteTarget` from the selected profile and revalidates signing inputs
before publication. Preserve/recover signing material before emptying a copied
seed for a fresh-add experiment.
[Target construction](../../src/iOpenPod/app/services/device_coordinator.py#L1262),
[HASH72 recovery](../../src/iOpenPod/app/services/device_coordinator.py#L3974),
[signing validation](../../src/iPodDB/library/_write_analysis.py#L209).

No runtime code, seed device, media file, or parent experiment script was modified
for this source investigation.

[original-podcast]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/podcasts/podcast_sync.py
[original-mhit]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py
[original-sqlite]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sqlitedb_writer/library_writer.py
[original-albums]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhla_writer.py
