# Podcast reading and writing from four Finder captures

Investigation date: **2026-10-18**. The user supplied copied iPod files under
`C:\Users\JohnG\Desktop\Podcast Research` and reported that Apple's current Finder
and Podcasts applications wrote the Podcasts. Exact application and firmware
versions were not supplied. The Classic 6.5 reportedly shows one **Root** entry;
none of the devices reportedly displays Podcast artwork, chapter artwork, or
chapters. These observations are evidence, not desired authoring behavior.

All capture access was read-only. No connected iPod was modified. Native database
and media-tag inspection used repository readers, Mutagen, and FFprobe; detailed
local observations remain in ignored `.scratch/podcast-capture-report.json` and
`.scratch/podcast-media-report.json`. Regression inputs are synthetic and contain
no captured media, publisher descriptions, device identities, or account data.
The Nano 5 directory also contains preexisting iOpenPod metadata, so the whole
copied directory should not be described as an exclusively Apple-created tree.
This does not contradict the reported provenance of its Podcast database/media.

See the [primary-source comparison](podcast-primary-sources.md) for pinned
Original iOpenPod/libgpod implementations and Apple's model-specific manuals.

## Capture inventory and reproducibility

Paths below are relative to each model's `iPod_Control/iTunes/` directory. Hashes
identify the exact private input; do not substitute a later device read silently.

| Model | Artifact | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Classic 6.5 | `iTunesDB` | 96,600 | `3b93db58f76c416149386d7fb5ab1729877befd1b20fc50c29985d63061568d5` |
| Mini 2 | `iTunesDB` | 88,034 | `85712832737f597f8ef6e5ea50be2b775bab1f130df84b20cf8f2086688569a4` |
| Nano 2 | `iTunesDB` | 88,722 | `94573be8f18ee3c22155b3c5ad0a6f5c0f8304c7951d6be8cd97398dfda92ad9` |
| Nano 5 | `iTunesCDB` | 17,591 | `f5134717215e190c47ae07acdb2cf5ef8390fc5f5fbcdd31991d1781dd04df15` |

For each input, `IPodLibrary(data).serialize().itunes == data` passed, including
physical CDB framing. Each catalog reconciliation recovered three shows and all
15 Episodes: Buzzcast (4), Murder With My Husband (5), and The Joe Rogan Experience
(6). All 60 media files across the four captures are MP3s.

The uncompressed databases contain datasets `4, 1, 3, 2, 5`; Nano 5's decompressed
CDB contains `4, 8, 1, 3, 5`. Every root reports version 117 and every MHIT has a
624-byte header, including Mini 2. These observations do not replace the selected
Device Profile's authoring policy with a universal version/header-size rule.

To repeat the investigation: hash the native input; unwrap CDB when needed;
inspect typed MHIT/MHYP/MHIP selections; compare the public Library Snapshot and
Podcast Catalog; inspect MP3 ID3 APIC/CHAP/CTOC frames; then compare native artwork
and chapter resources independently. SQLite files can be loaded into a private
in-memory connection with `deserialize`, without opening the captured database
for writes. Never use a test preparation result as authorization to publish it.

## Track metadata and native resources

The following observations apply to all 15 Tracks in each capture.

| Evidence | Observed value | Reading/writing implication |
| --- | --- | --- |
| MHIT media type | `0x05` | Audio plus Podcast; exact equality with `0x04` would miss these Episodes. |
| Podcast Now Playing marker | `1` | Preserve retained enabled values; the existing authoring policy already enables the marker. |
| Remember position / skip shuffle | `1` / `1` | Matches ADR-0092. |
| MHOD 3 / 4 | Show title / author | Track metadata is sufficient to recover the shows without trusting Playlist parent links. |
| MHOD 15 / 16 | Opaque Episode token / RSS URL | MHOD 15 was named “enclosure URL” before this investigation. The [subsequent virtual comparison](podcast-virtual-comparison-2026-10-18.md) confirmed a catalog matching defect; ADR-0149 adopts the GUID meaning. |
| MHOD 14 / 18 | Description / shorter subtitle | Preserve their distinct meanings and retained encodings. |
| Artwork count / size | `1` / positive | These hints alone do not establish a usable native cover. |
| Artwork-presence flag / reference | `2` / `0` | No resolved Artwork ID is available. |
| Native chapter MHOD 17 | Absent | No chapter positions are stored in these native Track records. |
| `iPod_Control/Artwork/` | Absent | There is no captured ArtworkDB or iTHMB material to display. |

Fourteen Tracks per capture have native not-played value 1 and one has value 2;
all stored play counts are zero. Nano 5 additionally has two nonzero bookmarks,
12,005 and 7,596 ms, in both bookmark fields. Preserve playback evidence rather
than marking every imported Podcast unplayed or discarding its resume position.

The captures demonstrate absent native resources despite positive artwork count
and size hints. They do not demonstrate that these iPods cannot show artwork or
chapters. Mini 2 lacks native cover capability; its iOpenPod display artwork remains
the separate policy in [ADR-0118](../adr/0118-write-application-artwork-for-non-cover-devices.md).

## Podcast Playlist structure and Root hypothesis

Every dataset-3 Podcasts Playlist has `playlist_kind_flags = 1`, three group MHIPs,
and 15 episode MHIPs. Each group precedes its Episodes and has flag `0x0100`,
Track ID zero, a unique nonzero group ID, and a type-1 show title. Each Episode
has its own nonzero row ID, and its type-100 position equals that row ID.
**All 15 episode `group_id_ref` values are zero on every model.** The separate
unknown u16 at MHIP `0x12` is also zero in these captures.

Follow-up on **2026-10-19** confirmed that all 12 show groups have an ID exactly
one below their first Episode's row ID, followed by consecutive increasing Episode
IDs. Gaps occur between shows. For example, Classic groups 8807, 8818, and 8836
precede Episode ranges 8808–8812, 8819–8824, and 8837–8840. The ordinary
counterparts use the same Episode row IDs. This agrees with the Original/libgpod
group-first allocation convention. It does not establish that Finder rejects all
other numbering, nor justify copying Apple's absent parent references.

The later **Classic 6.5 Apple PlayCount** capture breaks the apparent identity
between row IDs and positions: Episode row IDs are now 76–90, while both dataset
counterparts retain positions 8808–8812, 8819–8824, and 8837–8840. The user reports
that Finder accepts this capture. After restoring it and refreshing with
iOpenPod, **Classic 6.5 Latest** has positions 92–96, 98–103, and 105–108 in dataset
3, while dataset 2 still retains the Apple values. This establishes a counterpart
mismatch introduced by iOpenPod, not a Finder requirement that positions equal
current row IDs. The writer now preserves the flat value during repair and shares
it with the grouped Episode; whether the mismatch caused rejection still requires
a device test.

The ordinary dataset-2 counterparts, where present, contain 15 flat occurrences.
No inspected Playlist or group title contains literal `Root`. The database still
contains all three named groups on the Classic.

Original iOpenPod and libgpod write an explicit parent group reference on each
Episode. The missing links are therefore a concrete authoring difference and a
plausible explanation to test for the Classic's display. They are **not a proven
cause**: all four captures share them, but the user only reported Root on Classic
6.5. Do not invent a Root group or copy zero references into new authored groups.

The existing iPodDB writer already assigns parent links when membership or show
grouping changes. Synthetic regressions now verify this for both ordinary and
compressed inputs, retain surviving occurrence identities, and check that the
flat companion stays flat. Default no-op preparation preserves the original zero
references. Consequently, this increment does not claim that an unchanged Sync
automatically repairs the Classic's reported Root symptom.

A controlled hardware experiment should change only the uniquely resolvable
parent links, retain IDs, order, labels, media and playback state, sign correctly,
and publish through the recoverable Storage workflow. Compare the same firmware's
show list before and after. No such physical experiment was performed here.

## Embedded artwork and chapters

Every MP3 in every capture has a readable embedded cover. Four Buzzcast Episodes
also have ID3 chapters. Counts below occur in each of the four model directories.

| Episode | CHAP frames | Chapter APIC images |
| --- | ---: | ---: |
| How To Reduce Filler Words And Calm Your Nerves | 1 | 0 |
| Designing Podcast Cover Artwork That Gets Clicks | 22 | 10 |
| How to Choose the Right Monetization Strategy For Your Podcast | 12 | 1 |
| Apple's Big Changes For Podcast Chapters And Links | 5 | 1 |
| **Total per device** | **40** | **12** |

The new shared embedded-cover capture path decoded all 15 Classic sample covers.
`MediaInspector.scan_metadata` and `imported_chapters` read all 40 chapter markers
from its four chaptered files. One Episode has two differently titled markers at
1,007,300 ms; the first has a zero-length interval. The current reader preserves
both, and this research does not authorize dropping one by title or timestamp.

The file metadata establishes that these resources were available in the copied
media while the native databases did not contain their corresponding output.
Apple Podcasts can also obtain chapters outside a media file, so this finding
must not be generalized to every Podcast download. See the
[Apple chapter-source comparison](podcast-primary-sources.md#modern-app-chapters-need-not-be-embedded).

## Nano 5 SQLite cross-check

`Library.itdb` passes SQLite's integrity check and contains 15 items and 15
`podcast_info` rows. Every item has `media_kind = 5`, `is_song = 1`,
`is_podcast = 1`, remembered bookmarks and shuffle exclusion enabled,
`artwork_status = 2`, and `artwork_cache_id = 0`. Every Podcast row contains a
feed URL and external GUID. The Podcasts container has distinguished kind 11
and media kinds 5; the hidden Master and Podcasts container together have 30
membership rows. `Extras.itdb` has zero chapter rows and 11 lyrics rows.

This corroborates the CDB's missing native chapter/artwork resources. It does not
make SQLite an alternative read authority: CDB remains authoritative under the
[existing architecture](../source_architecture.md#common-library-interface).

## Implemented increment and remaining limits

Podcast Sync previously prepared show-level publisher covers but never extracted
an incoming Episode's embedded cover. It now reads that cover from the retained
Storage-owned download, so transcoding cannot erase the only cover source. A
usable embedded Episode cover takes precedence over the show cover; the existing
publisher loader supplies a fallback. Both sources share the 64 MiB retained
cover budget, bounded decoding, cancellation, and normal ArtworkDB publication.
Existing retained-Episode cover repair remains publisher-based and does not reread
device media. No dependency was added.

Generated MP3 integration tests verify saved cover pixels and native chapter
metadata after device reload, with pass-through and actual re-encoding. They also
exercise fallback from unusable embedded artwork. Synthetic database tests verify
compound Podcast classification, URL projection, unresolved artwork hints,
lossless no-op behavior, explicit group links after edits, ambiguous-ownership
rejection, and show recovery. Real-input metadata edits on Mini 2 and Nano 2 also
prepared successfully. Equivalent Classic/Nano 5 write probes stopped at the
required-signature gate; this investigation did not bypass that gate or publish
unsigned candidates.

This increment does **not** import nested chapter images into a timed Artwork
timeline or reread retained device MP3s to repair missing chapters. The shared
chapter reader currently carries titles and positions, not nested CHAP/APIC data.
That is a concrete next implementation boundary, using the existing timed-artwork
contracts rather than copying Apple's absent output. Publisher RSS chapter/image
URLs and server-generated chapters are also separate inputs. The Classic Root
hypothesis and model-specific chapter-artwork display still need physical testing.

Relevant regression files:

- `tests/iPodDB/library/test_finder_podcasts.py`
- `tests/iOpenPod/app/podcasts/test_finder_recovery.py`
- `tests/iOpenPod/app/test_podcast_embedded_artwork.py`
- `tests/iOpenPod/app/test_podcast_chapters.py`
- `tests/iOpenPod/app/podcasts/test_podcast_sync_artwork.py`
