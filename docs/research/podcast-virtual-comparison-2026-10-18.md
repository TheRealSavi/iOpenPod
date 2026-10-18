# Podcast Sync: four virtual iPods versus Finder captures

This is the before-change baseline. The requested fixes and regenerated virtual
devices are covered by the [verification report](podcast-fixes-verification-2026-10-18.md).

Measured on **2026-10-18** using the current working tree, based on commit
`f5a1a97919c50a552d282072b3be768ed4001626`, including the embedded Episode-cover
changes from the [capture investigation](podcast-finder-captures-2026-10-18.md).

All four virtual iPods successfully published and reloaded **15 Episodes from
three shows** through the actual iOpenPod Podcast Sync pipeline. Comparison found
additional identity, SQLite classification, metadata, and native-layout issues.
The strongest findings are a reproduced duplicate-catalog problem, missing Nano 5
Podcast container classification/GUIDs, and omitted explicit-content metadata.

## Experiment and controls

The original samples remain at `C:\Users\JohnG\Desktop\Podcast Research`.
Private scripts, captured RSS, normalized publisher inputs, generated volumes,
raw comparisons, logs, and SHA-256 manifests are under
`.scratch/podcast-virtual-comparison/`. These files include downloaded media and
private device data and are intentionally excluded from Git.

The final virtual volumes are under that directory's `devices-v2/`:

| Virtual model | Device Profile | Apple primary bytes | iOpenPod primary bytes | New MHIT header |
| --- | --- | ---: | ---: | ---: |
| Classic 6.5 | MB565, 120 GB | 96,600 | 118,973 | 624 |
| Mini 2 | M9802, 4 GB | 88,034 | 113,563 | 328 |
| Nano 2 | MA477, 2 GB | 88,722 | 113,563 | 328 |
| Nano 5 | MC046, 8 GB | 17,591 | 20,981 | 624 |

Nano 5 uses compressed iTunesCDB plus five SQLite databases and a Locations
checksum book. Other models use iTunesDB. Mini's model comes from its captured
SysInfo; Nano 5's normalized model comes from its Device Evidence. Classic and
Nano 2 use representative profiles for the named generations because their
captured SysInfo files are empty. Capacity/finish identification for those two is
an experiment assumption, not recovered evidence.

1. Fetched each publisher's feed with `FeedparserPodcastClient` and selected the
   exact 15 captured Episode titles, corroborating GUIDs where available. Saved
   the typed metadata and a subsequent raw RSS capture. The five Murder With My
   Husband GUIDs differ from Apple's tokens; the ten other GUIDs agree.
2. Created empty firmware templates from each captured database. Removed all
   Tracks, Album/Artist rows, Podcast playlists, memberships, and master browse
   indexes. Retained the root, dataset shells, master identity/header, and empty
   firmware category headers. Master titles became `Virtual <model>`.
3. Registered ordinary directories using `VirtualStoragePlatform`, with
   model-specific device/volume identities. Supplied synthetic FireWire GUID and
   Nano 5 HASH72 material, as appropriate for virtual-only publication.
4. Persisted subscriptions through `DeviceCoordinator.save_podcast_state` and ran
   `SyncExecutor.execute` with explicit selections, the real catalog/planner,
   media inspection, artwork preparation, iPodDB preparation, signing, and Storage
   transaction. Scrobbling was disabled.
5. Replayed each model's captured MP3 as its corresponding enclosure HTTP response.
   The real bounded download/capture code ran; these were **not fresh internet
   audio downloads**. RSS metadata was live. Smart Spoken Word and lossy
   retranscoding were disabled to isolate database authoring from audio changes.
6. Reloaded each virtual iPod through `DeviceCoordinator`, checked all 60 output
   MP3s against their source SHA-256 values, and compared native structures and
   SQLite rows after matching Episodes by unique normalized title and feed.

The first minimal seed, containing only an empty Track dataset, was rejected with
`playlist.podcast_capability`. The application currently edits provisioned
libraries; it has no blank-device initialization workflow. The final empty
firmware templates supply that required structure without supplying Episode
records. Template-preserved fields are not independent authoring evidence.

## Findings beyond artwork, chapters, and group references

### 1. Apple episode identities are misinterpreted during catalog recovery

All 15 Apple MHOD-15 values are opaque tokens, not HTTP enclosure URLs. Ten equal
the corresponding current RSS GUID exactly. All 15 Nano 5
`podcast_info.external_guid` values equal the corresponding captured MHOD-15
tokens. Apple has no MHOD-20 Episode string in these captures.

iOpenPod currently projects MHOD 15 into `podcast_enclosure_url` and reads an
Episode GUID only from `Track.episode` / MHOD 20. Fresh authoring writes the actual
HTTP media URL into MHOD 15 and the RSS GUID into MHOD 20.

A separate **read-only** execution of the actual catalog and planner proved the
consequence on every original capture:

| Operation | Result per model |
| --- | --- |
| Recover Apple catalog | 3 shows, 15 on-device Episodes; zero recovered GUIDs or HTTP enclosures |
| Merge the same 15 publisher Episodes | 30 catalog Episodes: 15 on-device and 15 off-device |
| Explicitly select those 15 fetched Episodes | 15 additions permitted, zero removals, zero reported issues |
| Reconcile device membership again | Same duplicate catalog and addition plan |

No duplicate downloads were executed against the originals. This is a confirmed
matching/planning defect, separate from the missing Podcast group references.
The fix should distinguish opaque identity evidence from a downloadable enclosure,
preserve existing URL-authored libraries, and avoid blindly equating changed
publisher GUIDs by title alone. The five changed GUIDs need corroboration and an
ambiguity policy. See the
[measured catalog trace and code references](podcast-authoring-comparison-notes.md).

### 2. Nano 5's generated SQLite Podcast metadata is incomplete

Both outputs have 15 `item` rows, 15 `podcast_info` rows, 15 `avformat_info` rows,
15 locations, and 30 playlist memberships. All five databases pass integrity
checks. Nevertheless, important values differ:

| Field or relationship | Apple | iOpenPod |
| --- | --- | --- |
| Podcasts container `distinguished_kind` | 11 | 0 |
| Podcasts container `media_kinds` | 5 | 1 |
| Master container `media_kinds` | 5 | 1 |
| `podcast_info.external_guid` | Populated for 15 | NULL for 15 |
| `item.media_kind` | 5 | 4 |
| `item.is_song` / `item.is_podcast` | 1 / 1 | 0 / 1 |
| Total containers / `container_ui` rows | 2 / 2 | 8 / 8 |

The six extra containers come from the retained firmware category playlists:
Music, Videos, Movies, TV Shows, Audiobooks, and Rentals. Their SQL projection is
distinct from the fresh Podcast container problem; do not conflate their count
with missing Episode memberships.

The [SQLite writer](../../src/iPodDB/SQLiteDB/database.py) explicitly inserts NULL
for the external GUID, recognizes only categories 4 and 5 as distinguished
containers, and otherwise uses a default media mask of 1. The newly created native
Podcasts playlist has `playlist_kind_flags=1`, but its field at MHYP offset 0x52
is zero; Apple stores 11 there. The shared definition currently calls that field
`phase_game_flag`. These observations justify investigating Podcast-specific
container metadata; they do not establish the full meaning of that native field.

This is a compatibility concern even though SQL integrity checks pass. Actual
Nano firmware navigation remains untested. The captured Nano 5 SysInfoExtended
contains no SQLite postprocessing command set, so omission of such commands is
not the cause of this comparison.

### 3. Explicit-content flags are dropped before writing

The six Joe Rogan Episodes have `explicit_flag=1` in Apple's MHITs and
`content_rating=1` in its Nano SQLite items. All six are zero in iOpenPod's output.
The fetched RSS explicitly marks all six `itunes:explicit=yes`.

This is a confirmed metadata omission, not a publisher-data absence:
[`PodcastEpisode`](../../src/iOpenPod/app/podcasts/models.py) does not carry the
advisory, and [`episode_track`](../../src/iOpenPod/app/podcasts/media.py) does not
supply one. Fixing only serialization would not address the loss.

### 4. Podcast flags agree, but classification and descriptive metadata differ

These results hold across all four generated databases:

| Observation | Apple | iOpenPod | Interpretation |
| --- | --- | --- | --- |
| Resume, skip shuffle, Podcast Now Playing | All 1 | All 1 | Agreement on essential Podcast flags |
| Native media type | 5, audio plus Podcast | 4, Podcast | Deliberate input policy; hardware comparison needed before changing |
| Episode number field | Zero for 15 | RSS number for 15 | iOpenPod retains more explicit Episode metadata |
| Season field, Murder With My Husband | Zero for 5 | 1 for 5 | Current RSS supplies season 1 |
| Disc number, same five | 1 | 0 | Different season/disc mapping |
| MHOD 19 / 20 / 22 | Absent | Show / GUID / album artist for 15 | Additional iOpenPod metadata |
| Year, Buzzcast | 2025 for 4 | Zero | Publication date exists, but year is not derived |
| Last modified | Populated for 15 | Zero | Fresh adapter does not supply this value |
| MHOD 18 subtitle | Present for 15 | Absent | Current Podcast input has no subtitle field |
| MHOD 28 sort album | Present for 6 | Absent | Joe Rogan's Apple sort name removes leading “The” |
| Native MHOD 10 lyrics | Absent | Present for 11 | Embedded text is imported; not necessarily a spoken transcript |

All 15 publication dates agree. Titles differ only by trimmed trailing whitespace
for three Episodes. Buzzcast category differs (`Tech News` versus `podcasting`);
that comes from current feed parsing/input and cannot be attributed to the writer
alone. All descriptions differ in formatting/content representation. Nano 5 Apple
stores a short HTML description and a populated long description; iOpenPod stores
its normalized description with NULL `description_long`.

### 5. Identical MP3s produce slightly different technical metadata

File size, sample rate, MP3/filetype/MPEG flags, and variable-bitrate flags agree
for all 15 Episodes on every model. Yet 11 durations differ by **1–53 ms** and six
bitrates differ: five are 256 versus 257 kbps, one is 96 versus 98 kbps.

The filler-words Buzzcast Episode has Apple's nonzero MP3 gapless values:
pregap 576, sample count 52,433,217, postgap 1,791, and encoder 1. iOpenPod's MHIT
values are zero. Apple sets `gapless_track_flag=1` for all 15; iOpenPod sets zero.
Nano SQLite similarly omits that Episode's delay/drain values, while deriving
sample durations for all Episodes from inspected media.

Because media bytes are identical, these differences belong to inspection and
metadata mapping, not audio conversion. They warrant a focused LAME/gapless
inspection check; the experiment does not prove an audible defect.

### 6. Native browse structures and model layouts differ

- Fresh Album rows: Apple has six MHIA records, all `content_type_flag=3`;
  iOpenPod writes three, all flag 2. Apple's records include two representations
  per show, while iOpenPod combines show, author, feed, and show metadata into one
  row. This merits firmware testing; copying duplicate Apple rows is not justified
  by count alone.
- Mini 2 and Nano 2 get 328-byte new Track headers; Classic and Nano 5 get 624.
  Apple uses 624 on all four. Every root remains version 117 because it was retained
  from the empty template. Header size follows Device Profile policy, independently
  of that retained root version.
- Nano 5 gains a dataset-2 counterpart: Apple `[4, 8, 1, 3, 5]`, iOpenPod
  `[4, 8, 1, 3, 2, 5]`. Other dataset sequences remain `[4, 1, 3, 2, 5]`.
- The new Podcasts playlist has sort order 0 versus Apple's 3, zero timestamps,
  and no MHOD-102 settings payload. Grouped and flat membership counts agree.
  Episode/show ordering follows the experiment's explicit selection order and
  first-seen grouping, so this run does not demonstrate a general chronology rule.
- Master browse indexes were intentionally removed from the seed. Their regenerated
  set differs from Apple's larger set; that observation is about rebuilding, not
  loss during unchanged reads. Retained empty firmware category headers are also
  template input, not independently authored evidence.
- Nano's schema contains additional columns in `item_stats` (`genius_id`), `album`
  (`item_count`, `has_movies`), and `genre_map` (`compilation_count_calc`). Apple has
  15 Store rows and one Genius configuration row; iOpenPod has neither. The extra
  schema columns and missing Apple-private state are separate from Podcast
  classification and should not be copied merely to make raw databases alike.

## Expected differences and excluded topics

Fresh Track/playlist/Album/Artist identities, physical media paths, insertion
order, new download dates, signatures, compressed sizes, and SQLite page layout
are expected to change. Compare relationships rather than numeric identity values.

Fresh downloads start unplayed. Apple has 14 `not_played_flag=1` Tracks, despite
zero play counts, and Nano 5 has two bookmarks. iOpenPod starts all 15 unplayed with
zero bookmarks. This run does not test migration of listening history.

Apple-private Store IDs and unknown fields were not supplied to new Podcast
Tracks; zero/default values there are not evidence of failed lossless preservation.
Classic regenerates the selected HASH58 signature and retains the other root
signature bytes; Nano regenerates HASH72 with synthetic material. This experiment
does not verify compatibility with the real devices' signing identities.

Artwork, chapter content, and Episode-to-show group references were excluded from
the findings above, as requested. Those resources still flowed through normal
Sync and affect sizes. The earlier
[capture report](podcast-finder-captures-2026-10-18.md) covers those differences.

## Verification and next implementation targets

All four Sync results are `success`, with only the expected timezone-fallback
warning from the synthetic Device Evidence. Each app reload finds 15 Tracks;
all four unchanged database roundtrips reproduce their bytes exactly. All 60
published MP3 copies match their source hashes. The four original primary
database hashes still match the initial investigation. Classic HASH58, Nano HASH72,
and Nano's Locations checksum book verify with the virtual signing material.
All ten inspected SQLite files, original and generated, pass integrity checks.

The comparison scripts did not change application runtime behavior. Prioritize
the confirmed identity/duplicate-planning issue, explicit-content propagation,
and Podcast-specific Nano SQLite metadata next. Follow with native Podcast Album
classification, descriptions/sort metadata, and MP3 gapless facts. Keep those as
separate changes with focused regressions and eventual physical-device checks.

Private evidence entry points: `verified-manifest.json`, `comparison.json`,
`sqlite-normalized-diff.json`, `catalog-matching.json`, `publisher-inputs.json`,
`rss-evidence.json`, and the four `*-v2-run.json` files. The
[source-expectations note](podcast-authoring-comparison-notes.md) connects these
observations to current and Original iOpenPod code.
