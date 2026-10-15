# Adjacent playback compatibility review

Investigation date: 2026-10-15. This note compares current iOpenPod after PR #249
with Original iOpenPod. It records software behavior and compatibility questions;
source agreement alone does not establish physical firmware acceptance.

## Pinned evidence

- Current iOpenPod: [`244bab9a8f2ce1c0dafd95beb30141e4f03ce614`][current].
- Original iOpenPod `origin/1.x`:
  [`a20242428b93b672d14b37230772dbad75139c69`][original].
- Additional reference: libgpod
  [`7982c5554f78dde47fd006afbeff659201d6db3d`][libgpod]. Its retained source copy
  under `.scratch/ithmb-research/database-fields/itdb_itunesdb.c` was inspected.
- Independent implementation: foo_dop / ipod_manager
  [`08e0657b5ee09bd05cdb60273e1a139205d4d3f6`][foo]. Its pinned playback reader
  and database writer were inspected. libgpod was also fetched again at the pinned
  revision to check the local reference. The historical iPodLinux format page
  could not be retrieved and is not used to settle an open question.
- Current contracts: [ADR-0100][adr100], [ADR-0144][adr144],
  [firmware playback sidecars][sidecars], and [Library writing][writing].

No production code or tests were changed for this research. Capture inspection
used read-only Python through UV. The coordinating review ran 35 bounded public
Library probes and 192 existing sidecar, projection, header, native-verification,
and artwork tests; all 192 tests passed. The probes below expose cases absent from
that existing coverage. No physical device write was run.

The subsequent implementation is recorded in
[ADR-0145](../adr/0145-select-track-layouts-for-all-library-writes.md). The failures
and policy differences below describe the pinned pre-fix revision, not the updated
implementation. Rating, bookmark, and ambiguous sidecar interpretations remain
separate research questions.

Original iOpenPod is a comparison baseline, not a specification. It shares format
research with libgpod; agreement between those two is weaker than independent
firmware evidence. Capture observations prove only what those files contain,
without proving every size or field accepted by their firmware.

| Topic | Evidence | Confidence and disposition |
| --- | --- | --- |
| Late composer/artwork fields bypass header expansion | Public Library failures and passing controls under the same capability | Confirmed software defect; fix next |
| New Track always gets 624 bytes | Source inspection and prepared output versus 1.x policy | Confirmed policy difference; firmware incompatibility unproven |
| Old rating backup remains unchanged | Prepared output differs from 1.x, libgpod, and foo_dop | Strong interoperability lead; establish native ownership and tests |
| Secondary bookmark remains unchanged | Current field mapping versus foo_dop, plus retained matching pairs | Synchronization-baseline contract needs a decision |
| Skip count in a 24-byte row | Sources disagree; available captures all use 28-byte rows | Unresolved; do not label as confirmed data loss |

## Confirmed defect: late native updates bypass header expansion

`edit_track` decides expansion before hidden Library indexes are reconciled.
`_composers` subsequently writes `composer_id`, and artwork reconciliation writes
`has_artwork` later still. Those later native fields do not participate in the
expansion decision. [Track-writing order][current-reconcile],
[composer assignment][current-composers], [artwork preparation order][current-preparation],
[artwork assignment][current-artwork]

The coordinating review reproduced these results through public Library
preparation with device database capability `0x30`:

| Edit | Source MHIT size | Preparation result |
| --- | --- | --- |
| Set Composer | 156 or 328 bytes | Fails `binary.short_header` for `composer_id` |
| Set artwork | 156 bytes | Fails `binary.short_header` for `has_artwork` |
| Same Composer or artwork edit, also set skip count to 2 | 156 bytes | Succeeds with a 624-byte edited MHIT |
| Set Composer | 504 or 624 bytes | Succeeds |
| Set artwork | 328, 504, or 624 bytes | Succeeds |

Adding skip history happens to trigger expansion early enough for the later
operation to fit. The same target therefore accepts the requested metadata only
when an unrelated field changes too. This is a preparation-order defect under the
already accepted device policy, independent of whether 1.x or another writer
chose the best size table. Preparation fails safely; the probe did not publish
partial output or consume device evidence.

The fix should include all intended native dependencies when deciding extent and
independently verify them afterward. The 328-byte / `0x19` Composer case also
fails, but its capability cannot authorize a 624-byte expansion: that needs an
explicit device-appropriate policy for the derived browse index, rather than
silently exceeding the capability. Keep no-op and unrelated retained fields
lossless. [Current capability boundary][adr144]

## Compatibility question: new Track header sizes

Original iOpenPod applies `mhit_header_size_for_version(db_version)` when it creates
every MHIT. Its version table selects 156, 328, 504, or 624 bytes. Current
`edit_track` accepts `database_version`, but creates a new MHIT through
`new_itunes_chunk` without supplying a size; the default is the largest supported
size. The device capability only participates later in expansion of a retained
short header. This is a concrete source-level difference for older Device
Profiles. [Original size selection][original-size], [current creation][current-new],
[current shared definition][current-mhit]

ADR-0144 explicitly left new Track creation unchanged, so this is adjacent work,
not a failure to implement that ADR. Public Library probes adding ordinary audio
with `WriteTarget.database_version` of `0x13`, `0x19`, `0x2D`, or `0x30` all
successfully emitted a 624-byte new MHIT; existing records retained their 328,
328, 504, or 624-byte source extents. Further checks should cover `0x0B`, Podcasts,
root versions, and fields outside a proposed extent. Any new rule must preserve semantic
intent or reject an unsupported field instead of copying the old writer's silent
omission behavior. Existing long headers and no-op serialization must remain
untouched. Physical rejection of an oversized record has not been demonstrated
by this investigation. [Expansion decision][adr144]

Independent writers do not establish the 1.x table as a universal maximum:
libgpod writes 584-byte MHITs and forces root version `0x30`; foo_dop selects
additional header fields using `is_6g_format`, rather than the same four-cutoff
table. The earlier [nano capture review][nano-captures] found 624-byte MHITs on
nano 5G/6G/7G, supporting that size for those captures but not establishing an
older model's rejection boundary. Changing new Track sizing should follow a
device/firmware fixture and acceptance matrix, not simply reproduce 1.x.
[libgpod writer][libgpod-size], [foo_dop writer][foo-writer]

Playlist creation does not expose a corresponding regression from 1.x: Original
MHYP writing uses a fixed 184-byte header, and the current MHYP definition also
uses 184. Neither establishes a separate older-device OTG Playlist size rule.
[Original MHYP definition][original-mhyp], [current MHYP definition][current-mhyp]

## Rating baseline differs from three reference implementations

When an incoming non-sentinel rating actually differs from the retained rating,
Original iOpenPod first copies the old rating into `app_rating`. libgpod does the
same. Neither changes that backup when the incoming rating already matches.
foo_dop independently follows that backup order for a changed rating, with its own
activity and sentinel guards. [foo_dop rating merge][foo-rating]
Current sidecar projection replaces only the semantic `Track.rating`; the native
`Track.ipod.app_rating` remains unchanged. Current SQLite projection writes that
retained value into `Dynamic.itdb.item_stats.user_rating_common`.
[Original rating merge][original-rating], [libgpod rating merge][libgpod-rating],
[current merge][current-merge], [current SQLite output][current-dynamic]

For example, source `rating=40`, `app_rating=20`, incoming rating `80` produces
`rating=80`, `app_rating=40` in the two reference merge implementations. The current
projection produces `rating=80`, `app_rating=20`; the coordinating public Library
probe also confirmed those values after preparation and reparse. This is a supported compatibility
lead, but its effect on a particular firmware or another sync client still needs
validation; the visible rating itself is updated. The same-rating case and binary
rating zero need separate checks because zero is deliberately treated differently
from 1.x. [Current rating policy][sidecars]

Any fix needs an explicit reconciliation-owned native dependency. `Track.ipod` is
documented as read-only native diagnostics, and current verification preserves
native fields without a corresponding semantic dependency. Making the entire
diagnostic object editable would weaken the existing contract. A regression test
should prepare and reparse a changed sidecar rating, inspect native `app_rating`,
and inspect the SQLite common rating for a late nano. Unrelated metadata edits,
unchanged incoming ratings, and no-op preparation should retain their native bytes.
[Field ownership][writing], [current field policy][current-policy]

## Bookmark mirror: investigate before normalizing retained bytes

Current semantic bookmark writes map to the primary field at `0x6C`. Header
expansion now seeds a newly exposed `bookmark_time_2` at `0xB4`, but an ordinary
bookmark update does not synchronize an already present second field.
[Field mapping][current-policy], [expansion seeding][current-expansion]

This is not established as a regression from 1.x. The Original shared definition
calls `0xB4` `unk0xB4`: its recorded Classic 6.5G capture had 33 nonzero values that
matched the primary bookmark, but the source explicitly calls its compatibility
role unconfirmed. Original `write_mhit` does not include it in the written values,
and libgpod treats it as opaque `unk180`. That evidence argues against blindly
updating every retained `0xB4` value. [Original observation][original-bookmark],
[Original writer][original-size], [libgpod opaque value][libgpod-bookmark]

foo_dop supplies independent evidence for a synchronization relationship: its
sidecar merge updates both `bookmarktime` and `bookmark_time_ms_common`, and its
writer places the common value at `0xB4`. That does not establish a universally
live mirror; a common or synchronization-baseline field may intentionally differ
between workflows. Decide ownership before normalizing retained mismatches.
[foo_dop bookmark merge][foo-bookmark], [foo_dop writer][foo-writer]

A useful follow-up is a controlled firmware capture before and after seeking an
Audiobook or Podcast, with both MHIT words and any SQLite bookmark fields recorded.
Current SQLite output already writes the semantic bookmark into both SQLite
bookmark columns. Test a matching native pair, a noncanonical mismatched pair,
explicit bookmark clearing, and new Tracks separately before adopting a mirror
ownership rule. [Current SQLite output][current-dynamic]

Read-only inspection of retained databases provides a reason to preserve those
distinctions. The table reports actual parsed pairs, with no Track names or other
media metadata. These files have device-labeled directories but no independently
verified writer/firmware provenance, so they cannot establish acceptance limits.

| Capture directory | Parsed Tracks | MHIT extent | Nonzero bookmark pairs that differ | Rating pairs that differ |
| --- | --- | --- | --- | --- |
| `Photo` | 191 | 624 | 0 | 0 |
| `Nano1` | 184 | 624 | 0 | 0 |
| `ipod3` | 193 | 584 | 0 | 0 |
| `Nano6` | 522 | 624 | 0 | 0 |
| `orig_nano7` | 832 | 624 | 9 | 1 |
| `nano5/MINE` | 51 | 624 | 0 | 1 |

Every equal bookmark pair in these six inspected captures was zero. In particular,
the nano 7 capture contains differing bookmark values already; treating `0xB4`
as an always-equal mirror would normalize real retained data. The earlier Classic
observation of matching nonzero values has a different evidence scope. The sampled
`nano2`, `nano4`, and `Classic6.5/skepiTunesDB` files yielded no typed Track records
and were excluded from this comparison rather than treated as empty-device proof.

The inspected files were `Photo/skepiTunesDB`, `Nano1/skep_iTunesDB`,
`ipod3/skepiTunesDB`, `Nano6/myiTunesCDB`,
`orig_nano7/iPod_Control/iTunes/iTunesCDB`, and
`nano5/MINE/iPod_Control/iTunes/iTunesCDB` under the retained capture directory.
The current low-level parser was used, with CDB decompression where detected.

## A 24-byte Play Counts row is an unresolved format difference

Original iOpenPod reads `skip_count` once a row is at least 24 bytes, and reads the
skip date at 28 bytes. Current iOpenPod waits for 28 bytes before interpreting
either field. Its tests explicitly encode that choice. libgpod's reference reader
also requires 28 bytes for both, so the difference from 1.x does not by itself
prove a defect. [Original reader][original-counts], [current reader][current-codec],
[current reader tests][current-codec-tests], [libgpod reader][libgpod-counts]

A pure authored reproduction with a 96-byte `mhdp` header and one 24-byte row
containing `7` at byte offset 20 returns `skip_count=0` in current iOpenPod while
retaining the original file byte-for-byte. The zero is therefore an interpretation
decision, not a parser framing failure. Selection would archive that uninterpreted
value under the current Unknown Data contract. A real-device capture establishing
the meaning of that word in 24-byte rows is needed before changing the reader.
[Current codec][current-codec], [Unknown Data archive policy][adr100]

Read-only inspection of the retained capture directory
`C:/Users/JohnG/Coding/ipods` found three binary `Play Counts` files. All had
96-byte headers and 28-byte rows, with 51, 4, and 4 entries respectively; none
provides evidence for a 24-byte row. The separate device-folder `PlayCounts` file
is not an `mhdp` capture and was not interpreted as one.

The three binary sidecars also contained no `0xFFFFFFFF` bookmark values: their
51/4/4 rows contained 51/2/2 zero bookmarks and 0/2/2 nonzero finite bookmarks.
foo_dop's bookmark sentinel handling therefore remains a source-level difference,
not a captured example of a current selection failure. This check does not justify
changing the explicit current zero-bookmark contract. [Current contract][sidecars],
[foo_dop bookmark handling][foo-bookmark]

| Capture-relative path | SHA-256 |
| --- | --- |
| `nano5/MINE/iPod_Control/iTunes/Play Counts` | `15f9770399a5bcc5b4492a6e4eeb8db1a2a86485bb25c89e88c100b4c89cca59` |
| `nano5/USER2/iPod_Control/iTunes/Play Counts` | `9a758742f1d9ce6b733bf5a3b01614e16c2c19ec28d925f122a2a58d10486f75` |
| `nano5/USERS/iPod_Control/iTunes/Play Counts` | `cb667840f95214065b62947ff14c592dce8e6935aaa5295098f23499cc38504a` |

## Existing handling to retain

- Plays and skips accumulate independently; pending scrobbles accumulate only new
  plays. Both implementations preserve pending counts on unmatched trailing Tracks.
  Current projection also checks overflow. [Original merge][original-rating],
  [current merge][current-merge]
- Current sidecar replacement reprojects from the retained database and commits
  through Storage before publication. Its archives, malformed-input rejection,
  competing-source rejection, and recovery rules intentionally improve on 1.x;
  they are not missing compatibility fallbacks. [Current lifecycle][adr100]
- Binary rating zero intentionally clears a rating in 2.0, while plist zero is
  unspecified. Nonzero bookmarks override prior positions; zero remains
  unspecified. These are explicit contracts, not accidental omissions to restore
  from 1.x. [Current semantics][sidecars]
- Current OTG import retains duplicate occurrences and distinct equal Playlists,
  handles numeric gaps, and requires the base-file semaphore. The Original reader
  stops at the first missing numbered file and derives identities from content.
  Copying that behavior back would regress the current importer.
  [Original OTG reader][original-otg], [current OTG import][current-otg]
- Current code supports both Shuffle iTunesStats layouts and persistent-ID plist
  counts. The Original loading code reads binary `Play Counts`, although its
  cleanup list also names the other playback files. The legacy cleanup list is
  not evidence of equivalent interpretation support.
  [Original load][original-load], [Original cleanup][original-cleanup],
  [current readers][current-codec]

The two retained Shuffle iTunesStats captures parsed successfully as 24-bit
records: 109 rows with 557 total plays, and one row with 168 plays. Both serialized
to their exact input bytes. Their SHA-256 values are
`add99f81208c2fb21f760da65a3d7e6ab415451dd72fdaa8a675eaed1c060965` and
`97e6288852141d617fdf55423e0369b717cea90ffc3650b014bc9e59a8ebdcfc`, respectively.
This validates those captured layouts only; the undocumented Shuffle `skipped`
value should remain diagnostic until its meaning is established.
[Current Shuffle contract][sidecars]

## Implementation research: explicit output layouts

The implementation follow-up should fix the preparation-order defect and select
new Track layouts deliberately. It should not promote the 1.x version table into
a claim about physical firmware maximums. The following distinctions are supported
by the pinned source and captures.

### What the version table establishes

Original iOpenPod's authored MHIT sizes are 156 bytes through version `0x12`,
328 through `0x19`, 504 through `0x2D`, and 624 thereafter. Its root writer uses
the higher of retained root version and Device Profile baseline before passing
the selected version to MHIT writing. Therefore even 1.x can produce a 624-byte
MHIT for a device whose baseline is `0x13` when its retained root is newer.
[Original table][original-size-table], [Original version selection][original-version]

These exact cutoffs are not independently corroborated by libgpod. Its reader
documents 156-byte records through version `0x0B`, then 244-byte records at `0x0C`
and `0x0D`; its writer uses 584-byte records. The current Device Registry's
physical profiles use `0x13`, `0x19`, and `0x30`, so those profiles select 328 or
624 under the current project table. The 156/504 cases remain compatibility/helper
inputs rather than currently selected physical-profile outputs.
[libgpod historical layouts][libgpod-history], [current catalog][current-catalog]

The conservative implementation choice is to label this explicitly as the
project's *authoring policy*, retain the existing table for known profiles, and
test both creation and expansion against that same policy. Missing explicit
capabilities must not permit a retained header to expand based only on its root
version. Preserving a larger or nonstandard retained record is a different
operation from selecting the layout of a new record. A future change to the
`0x0C`/`0x0D` policy needs a separate decision rather than silently asserting that
the 1.x mapping describes historical layouts accurately. [Current boundary][adr144]

### Field extents and ownership

The following ends come from the shared MHIT definition and agree with the
Original field declarations. libgpod independently writes album ID at `0x120`,
the root-ID reference at `0x124`, secondary size at `0x12C`, artwork link at
`0x160`, artist ID at `0x1E0`, and composer ID at `0x1F4`.
[Current fields][current-mhit-fields], [Original extended fields][original-extended],
[libgpod extended fields][libgpod-extended]

| Native field | End, exclusive | Fits 156 | Fits 328 | Fits 504 | Handling when absent |
| --- | --- | --- | --- | --- | --- |
| `skip_count` / `last_skipped` | 160 / 164 | No | Yes | Yes | Semantic history; expand when authorized or fail, never discard |
| `has_artwork` | 165 | No | Yes | Yes | Artwork-owned dependency must participate in extent planning |
| `db_track_id_2` | 176 | No | Yes | Yes | Optional duplicate of the primary identity; initialize only where supported |
| `not_played_flag` | 179 | No | Yes | Yes | Existing short-format play-count fallback remains valid only when it represents intent |
| `bookmark_time_2` | 184 | No | Yes | Yes | Keep existing synchronization-baseline policy; do not normalize retained values |
| `media_type` | 212 | No | Yes | Yes | Default audio is implicit when absent; a nondefault requested type must be representable |
| `album_id` | 292 | No | Yes | Yes | Optional browse reference; reconcile consistently with an existing album dataset |
| `db_id_2_ref` | 300 | No | Yes | Yes | Optional native root reference; retain existing policy and bytes |
| `size_2` | 304 | No | Yes | Yes | Optional duplicate size; primary size already represents the semantic value |
| `sort_mhod_indicators` | 316 | No | Yes | Yes | Derived presence flags; any older-format omission must be explicit and leave MHOD intent intact |
| `artwork_id_ref` | 356 | No | No | Yes | Direct artwork reference is device-specific; retain supported reverse-link behavior on older models |
| `video_flag_2` | 405 | No | No | Yes | Optional native mirror; only authored where layout supports it |
| `artist_id_ref` | 484 | No | No | Yes | Optional browse reference, coordinated with the artist dataset |
| `composer_id` | 504 | No | No | Yes | Optional browse identity; Composer text remains an independent MHOD 12 |

Original writing silently skips every field whose minimum extent exceeds the
chosen header. That explains why it can create a 328-byte Track with Composer
text while omitting its later native composer ID; it does not justify making
2.0's binary writer silently discard arbitrary requested values. Named optional
derived fields should be deliberately absent when the selected format lacks
them. Direct semantic values, understood sidecar deltas, and existing native
references need separate validation and lossless preservation.
[Original bounded writer][original-bounded], [Composer text in libgpod][libgpod-composer-text]

Existing larger records on an older profile must keep their native extent and
references. When a short record can expand under the selected capability,
composer, album/artist, artwork, metadata, and media updates all need to contribute
before a final size is selected. Independent verification must apply the same
ownership distinctions: omitting a newly generated optional composer ID on a
328-byte new Track is different from clearing an existing nonzero ID. Unknown
bytes, partial opaque prefixes, and numeric-boundary rejection remain required.
[Current lossless decision][adr144], [current browse verifier][current-group-check]

### Adjacent Chunk headers

Original iOpenPod fixes MHBD at 244 bytes, MHYP at 184, and MHIP at 76; no
version-dependent sizing branch was found for these three types. libgpod agrees
on MHBD and MHIP but writes a 108-byte MHYP. This shows writer variation rather
than an evidenced older-device MHYP rule. The six parsed capture sets above all
use MHBD 244, MHYP 184, and MHIP 76. No additional per-device header special case
for those types is established by this investigation.
[Original root definition][original-root], [Original Playlist definition][original-mhyp],
[Original entry definition][original-entry], [libgpod Playlist header][libgpod-playlist],
[libgpod entry header][libgpod-entry]

Capture root versions were `0x75` for Photo and Nano1, `0x4F` for iPod3,
`0x6F` for Nano6, `0x75` for nano7, and `0x73` for nano5. Their MHIT extents were
624 except the 584-byte iPod3 capture. Preserve those original extents and root
versions during no-op or unrelated edits; neither the directory label nor a
source root version alone is authority to rewrite every record.

The recommended test matrix covers ordinary new Tracks at each policy extent;
short-header Composer and artwork edits independently and together; hidden
album/artist assignments; missing capabilities; optional field omission without
semantic loss; preserved larger headers; and complete no-op byte equality.
Physical acceptance remains a separate device/firmware check, especially for
choosing a new layout that differs from a device's retained population.

The implementation follow-up also parsed and serialized all six retained captures
through the public Library interface. All reproduced their complete input bytes
exactly, including compressed framing, across 1,973 Tracks. The original audit's
composer/artwork probes now prepare successfully with or without the unrelated
skip-count edit; new Track probes select 328, 504, and 624 bytes from their explicit
targets. These read-only checks establish regression behavior and preservation,
not physical firmware acceptance.

[current]: https://github.com/TheRealSavi/iOpenPod/tree/244bab9a8f2ce1c0dafd95beb30141e4f03ce614
[original-size-table]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L32-L44
[original-version]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhbd_writer.py#L367-L384
[libgpod-history]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2467-L2473
[current-catalog]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/device_registry/data/catalog.py#L138-L375
[current-mhit-fields]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py#L34-L117
[original-extended]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L113-L227
[libgpod-extended]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4079-L4117
[original-bounded]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/field_base.py#L394-L429
[libgpod-composer-text]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L5147-L5154
[current-group-check]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_group_verification.py#L246-L310
[original-root]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhbd_defs.py#L13
[original-entry]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhip_defs.py#L11
[libgpod-playlist]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L5495-L5497
[libgpod-entry]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L5052-L5066
[original]: https://github.com/TheRealSavi/iOpenPod/tree/a20242428b93b672d14b37230772dbad75139c69
[libgpod]: https://github.com/gtkpod/libgpod/tree/7982c5554f78dde47fd006afbeff659201d6db3d
[foo]: https://github.com/reupen/ipod_manager/tree/08e0657b5ee09bd05cdb60273e1a139205d4d3f6
[foo-rating]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/reader_playcounts.cpp#L283-L289
[foo-bookmark]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/reader_playcounts.cpp#L260-L264
[foo-writer]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/writer_itunesdb.cpp#L627-L781
[libgpod-size]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L3864-L3974
[nano-captures]: short-track-headers-and-playback-history.md
[current-reconcile]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_reconcile.py#L122-L137
[current-composers]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_hidden_writing.py#L410-L461
[current-preparation]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_write_preparation.py#L584-L598
[current-artwork]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_artwork_writing.py#L925-L938
[adr100]: ../adr/0100-reconcile-firmware-playback-sidecars-on-device-selection.md
[adr144]: ../adr/0144-expand-track-headers-with-device-capabilities.md
[sidecars]: ../playback-sidecars.md
[writing]: ../library-writing.md
[original-size]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py#L366-L512
[current-new]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_track_writing.py#L246-L270
[current-mhit]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py#L121-L145
[original-mhyp]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhyp_defs.py#L13
[current-mhyp]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/iTunesDB/shared/chunk_defs/mhyp.py
[original-rating]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/playcounts.py#L226-L277
[libgpod-rating]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2728-L2755
[current-merge]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_sidecar_projection.py#L27-L83
[current-dynamic]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/SQLiteDB/database.py#L651-L675
[current-policy]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_field_policy.py#L64-L144
[current-expansion]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_track_header_expansion.py#L47-L66
[original-bookmark]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L129-L132
[libgpod-bookmark]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4045-L4051
[original-counts]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/playcounts.py#L174-L180
[current-codec]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/sidecars/codec.py
[current-codec-tests]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/tests/iPodDB/sidecars/test_sidecar_readers.py#L57-L70
[libgpod-counts]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L1006-L1013
[original-otg]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/otg.py#L91-L187
[current-otg]: https://github.com/TheRealSavi/iOpenPod/blob/244bab9a8f2ce1c0dafd95beb30141e4f03ce614/src/iPodDB/library/_sidecar_projection.py#L130-L167
[original-load]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_db_io.py#L119-L137
[original-cleanup]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_db_io.py#L467-L480
