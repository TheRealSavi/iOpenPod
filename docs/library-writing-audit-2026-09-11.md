# Library writing investigation, 2026-09-11

The reported album-edit failure is reproduced and fixed. The wider investigation
also fixed stale album browse metadata and missing native relationship checks.
The audit does **not** establish full iTunesDB or ArtworkDB compatibility.
Initial reproductions used generated in-memory databases and virtual Storage
fixtures. Follow-up work captured a connected iPod and exercised its real
save/recovery path, as described below. The exact original failed draft was not
captured.

## Reported failure

The screenshot reports inconsistent ordinary Playlist occurrence positions on the
system-managed Podcasts Playlist after changing a music album's name. The supplied
log records stage entry but omits the actual issue and its causes.

The reproduction uses three Podcast episodes with albums A, B, A and titles that
sort into a different order, plus an unrelated music Track. The loaded Podcasts
Playlist is grouped A, A, B and carries native episode IDs as positions.

1. `LibraryWorkspace.apply_track_edits` called `_refresh_field_sorted_playlists`
   after any metadata edit. That function also sorted the system-managed Podcasts
   Playlist and replaced its native positions with ordinary positions.
2. Resolution grouped those occurrences by album again, retaining their now-stale
   positions. This explains the unexpected Playlist edit and grouping warning.
3. Reconciliation mapped the occurrences to dataset 2 but carried the position
   values across. `edit_playlist` trusted those values when writing MHOD 100.
4. Verification correctly rejected the malformed flat counterpart. The
   `source.recheck` stage was not the reported failure; database verification had
   already withheld the candidate.

The writer defect also reproduces directly through `IPodLibrary` by merging two
Podcast album names, without involving the Application Layer.

The fixes exclude system-managed Playlists from application sorting and generate
ordinary occurrence positions from the final order. Dataset 3's Podcast pass then
assigns native episode IDs to its own position records. Unchanged Playlists retain
their bytes, order, and occurrence metadata.

Regression evidence:

- `test_music_album_edit_preserves_system_podcasts_and_prepares` exercises the
  workspace-to-Library path and asserts no requested or generated Playlist edit.
- `test_album_merge_regroups_podcasts_with_valid_flat_mirror_positions` checks
  native positions independently in both reparsed datasets.

## Additional verification fixes

Podcast verification accepted multiple position records if **any** one matched the
episode ID. Injecting a correct position plus a conflicting position of 999 still
produced a Prepared Library. Verification now requires every position record to
agree. Failures report the dataset, Playlist, Track/occurrence, expected and actual
positions, artifact, and native item offset.

A second injection changed ArtworkDB's image source size during an album-only
edit. Reparse and semantic Track comparison accepted that unrequested change.
Preparation now rejects changed ArtworkDB bytes or generated artwork files when
neither artwork selections nor ownership changed.

`test_album_rename_preserves_shared_artwork_bytes_ranges_and_native_links`
establishes the intended behavior: identical ArtworkDB bytes, native Track artwork
links/counts and retained iTHMB ranges, with no new image files.

## Native browse fixes

### Verify native browse relationships independently

An injection replaced a reconciled Track's `album_id` with 999 while the only album
row had ID 5. Before this fix, `IPodLibrary.prepare` still returned a Prepared
Library. This was a verification gap, not evidence that the user's reported edit
itself generated a dangling album reference.

In `_write_preparation.py`, Track comparison replaces expected `ipod` diagnostics
with actual reparsed diagnostics. Generated values need this treatment only when a
separate native check verifies them. `_write_verification.py` checks Playlist Track
references, unknown datasets, photos, and artwork ranges, but does not independently
validate album/artist/composer references, group metadata, or representative Track
ownership. This was weaker than the verification intent in ADR-0024/ADR-0025.

The new `_group_verification.py` checks reparsed native records directly against
source identities and desired semantic groups. For affected groups it checks a
single nonzero reference, exactly one matching native record, retained identities,
SQL identity preservation, album/artist metadata, representative membership, and
album flags. Composer checks cover retained identities, shared ownership, and new
allocation conflicts. It does not call reconciliation or accept its output as an
expected value. Failures include the Track, field, artifact, offset, and expected
versus actual relationship.

Unrelated edits preserve source references, including missing references and
duplicate native rows. Changed groups with repeated native records are blocked
explicitly instead of silently choosing a row. Album and artist datasets remain
optional for older source formats.

### Refresh all affected album browse metadata

A generated source had an MHIA album row with MHOD 202 `Old sort`. Changing the
Tracks' album to `Renamed` and `metadata.sort_album_artist` to `New sort` prepared
successfully, but the album row still contained:

```text
MHOD 200: Renamed
MHOD 201: Artist
MHOD 202: Old sort
```

Previously `_hidden_writing.reconcile_hidden` wrote album MHODs 200/201,
compilation, season, and representative identity. Its impact test used group
membership and identity, so sort-only edits did not refresh the row either.
Original iOpenPod's `mhla_writer.write_mhla` also derives MHOD 202 (sort album artist
with sort artist fallback), 203 (Podcast RSS URL), and 204 (show name).

Reconciliation now maintains MHODs 200–204 and compares group metadata inputs as
well as membership. In Library Track order, it selects the first nonempty sort
album artist, falling back to the first nonempty sort artist, and the first
nonempty Podcast RSS URL. The show comes from the group's shared show identity.
Absent empty optional fields stay absent; existing stale values are cleared.
Draft effects include these field dependencies and Track-order changes.

`test_browse_relationships.py` covers sort/RSS-only changes and album renames, show
and fallback values, first-nonempty selection and Track reordering, split/merge
identities, deletion of representative Tracks, unrelated source anomalies, and
injected native reference/metadata corruption.

## Baseline comparison

Baseline checkout: `C:\Users\JohnG\Coding\iOpenPod`. Original source paths below
are relative to `src/iopenpod/` unless noted. No runtime or test dependency on that
checkout was added.

| Area | Original evidence | Result in iOpenPod 2.0 |
| --- | --- | --- |
| Ordinary positions | `itunesdb_writer/mhyp_writer.py`, `mhip_writer.py`: enumerate from zero | Fixed final-order positions, checked in both datasets. |
| Grouped Podcasts | `_build_podcast_grouped_mhips`: show groups, references, episode IDs in MHOD 100 | Separate dataset-3 reconciliation retained; conflicting position records rejected. |
| Dataset meaning | `docs/research/ipod-playlist-datasets.md`: datasets 2/3 versus categories in 5 | Existing tests cover mirrors, Master order, categories, duplicates, and dataset-2-only sources. |
| Album identity | `itunesdb_shared/album_identity.py`: album/show match; album artist if both present, otherwise artist | Current grouping adds compilation/season and uses one album-artist-or-artist key. This baseline divergence needs an explicit decision and was not silently changed. |
| Album metadata | `itunesdb_writer/mhla_writer.py`: metadata 200–204 and representative identity | Shared metadata selection, affected-row updates, and native verification fixed and tested. |
| Artist/composer identity | `itunesdb_writer/mhli_writer.py`: shared browse identities and case-insensitive artist deduplication | Affected references now verified. Current exact artist grouping remains a documented baseline divergence. |
| Artwork ownership | `artworkdb_writer/artwork_writer.py`: persistent Track identities and image references, preserving existing art for metadata edits | Metadata-only byte/link preservation tested; unexpected ArtworkDB mutations blocked. Existing tests cover shared-image replacement, clearing reverse links, and photos. |
| Artwork file records | `artworkdb_writer/artworkdb_chunks.py`: MHII/MHNI/MHIF and image extents | Existing tests cover ranges, retained prefixes, shard allocation, malformed resources, and packed pixel vectors; not every firmware/layout. |
| Signatures | `itunesdb_writer/hash58.py` and fixed captured vectors | HASH58 tests retained. HASH72/HASHAB, compressed/SQLite output, and signed ArtworkDB remain explicit blockers. |
| Unknown Data | Captured Original iTunesDB/ArtworkDB fixtures | Exact no-op and preservation tests retained. |

## Debug logging

The file handler already records DEBUG; missing observations were the problem.
This extends ADR-0023's phase-only logging policy as recorded in
[ADR-0028](adr/0028-record-library-write-debug-diagnostics.md). Logging now includes:

- Application attempt, workspace generation/revision, source fingerprints, stage
  entry times, stale-result rejection, and complete preparation/save issues.
- Source revision, requested versus generated changes, dotted field paths and
  bounded before/after values, effect causes, and resource requirements.
- Target/signature mode, sidecar inventory state, resource counts, native dataset
  and Playlist work, and artwork preservation/encoding decisions.
- Candidate/final artifact sizes and SHA-256 fingerprints, including candidates
  subsequently rejected by verification, plus stage durations and final state.

Raw databases, image pixels, and signing identity bytes are not dumped. DEBUG
records include selected metadata values; ordinary INFO output stays concise.
Tests check successful and blocked diagnostics and INFO-level behavior.

## Validation limits

### Follow-up native Track verification

Fault injection during a title edit changed codec flags, secondary file size,
floating sample rate, and secondary persistent identity. The candidate still
passed semantic comparison because that comparison substituted the reparsed
`ipod` diagnostic record. Similar failures reproduced for additions and media
replacements. Source and resource validation before serialization could not detect
corruption introduced afterward.

`_track_verification.py` now compares reparsed native media facts against the
captured `PreparedMedia` or unchanged native source values, and verifies retained
identities and new persistent identity uniqueness. Optional secondary fields and
noncanonical source values remain unchanged when their dependencies do not change.
Thirty regression cases cover corruption, correct preparation before injection,
and source preservation. Fifteen additional public API lifecycle cases exercise
every `MediaType` classification through add, metadata/chapter edit, media
replacement, and removal. Their simulated payloads do not establish codec validity
or support for each classification on each device.

### Captured-device evidence and provenance

The connected device identifies as MB565, iPod Classic 6.5th Gen. Its active
iTunesDB is 1,000,569 bytes (544 Tracks, five Playlists); matching ArtworkDB is
440,744 bytes. Read-only Storage capture also includes its four iTHMB files and
one music and one Podcast media file, with source hashes and rechecked file
fingerprints. Metadata edits, Podcast deletion, and clearing artwork prepare
successfully against this source.

The separate 20,138,994-byte iTunesDB (6,541 Tracks, 83 Playlists) belongs to a
**different iPod**, as confirmed by the user. It is useful only for self-contained
database checks. The connected device's ArtworkDB, media paths, and signing
identity are not evidence for that library. Historical candidate tests use a
synthetic signing target and remain on the Host. Missing or mismatched external
files for that database are expected and are not writer defects.

With the matching capture, replacing a cover and adding a Track with a new cover
both produce verified candidates. The four output iTHMB files retain their complete
source prefixes. These initial candidates remained on the Host; the later
application artwork/removal test below exercised actual device publication.

A separate authorized physical test renamed an album on 12 music Tracks, prepared
through `DeviceCoordinator`, and saved the issued review through Storage. Read-back
matched the candidate. `restore_replacement` restored the exact original iTunesDB
bytes, and a full device flush succeeded. All captured companion files, ArtworkDB,
iTHMBs, and media remained unchanged. The recovery journal is retained; the active
database has its original content but a new filesystem fingerprint. This proves
the tested persistence/recovery path, not playback or browsing by physical firmware.

### Work still required

- Resolve supported native grouping policy and remaining differences from Original
  iOpenPod before claiming album/artist identity compatibility.
- Historical MHOD 52 sort 36 is now supported through captured album traversal
  and Master Playlist coordinates. The earlier comparison incorrectly interpreted
  index entries as MHIT-table positions. Its artist-rule conclusions are withdrawn.
  See the [sort-36 investigation](research/itunesdb-sort-36.md) for corpus evidence,
  supported comparisons, preservation rules, and remaining evidence limits.
- Add actual media inspection/conversion and device capability validation, including
  media without an audio stream; connect captured resources to application drafts.
- Complete incoming media capture/import/replacement, cover-file selection, and
  application recovery controls. Captured artwork changes and Track removals now
  use reviewed Storage Transactions, as described below.
- Reconcile pending playback sidecars and implement required signature/companion
  formats with primary evidence, captured fixtures, and independent verification.
- Extend large-library and device tests to actual firmware behavior without treating
  successful reparse as proof of compatibility.

### Storage Transaction follow-up

ADR-0029 defines ordered multi-file publication with retained originals, delayed
removals, unchanged dependencies, capacity validation, and explicit recovery over
an inspected journal. The implementation holds one Volume writer lease throughout
publication or restoration and streams Host inputs. A callback that attempts to
write from the same thread now receives `DeviceBusyError` instead of deadlocking;
writers on other threads continue to wait for the lease.

Fault injection found that checking staged files before the final preparation
callback could publish earlier files before discovering a changed later stage.
The complete staged set is now rechecked after that callback. Restoration also
preflights space for the largest required original before modifying any target.

Storage tests cover each native rename during publication and restoration,
reconnection, interrupted and repeated restoration, stale observations, unrelated
edits, corrupt retained originals, malformed journals, path conflicts, capacity,
cancellation, streaming Host input, and writer serialization. The focused Storage
run passes 138 tests with one Darwin-only skip, including a same-size changed Host
input rejected by its captured SHA-256 before any target publication.

An authorized physical transaction test used synthetic files under a unique device
directory. It verified publication order, restored the original synthetic content,
then restored all test files to absence. The 26 captured device files retained
their exact pre-test fingerprints; no existing Library or asset was modified.
Volume flushing succeeded. Journals, recovery content, and the empty test directory
remain retained. This is filesystem transaction evidence, not media import or
firmware compatibility evidence.

### Application resources and reviewed file transactions

ADR-0030 binds each exact issued Library Review to a privately retained Storage
Transaction. Preparation captures artwork inventories and eligible source
thumbnail prefixes, fingerprints removed-media dependencies, checks pending
positional sidecars, and validates capacity. Shared media remains when any retained
Track still references it. Missing removed media is captured as an absence rather
than treated as permission to remove a subsequently appearing file.

The workspace retains supplied artwork assets and explicit Track-deletion intent.
Clear Artwork and Remove from Library are reversible draft actions. The review
lists the actual file writes and removals. Save publishes thumbnails, ArtworkDB,
and iTunesDB, verifies writes, then moves obsolete media into recovery. It rechecks
source identity and sidecars at the final preparation boundary. Only a committed,
verified result becomes the authoritative application Library. An older concurrent
preparation, copied review, or stale review cannot gain save authority.

Tests cover artwork replacement and clearing, shared image/media ownership,
removals, stale thumbnails, newly appearing sidecars, cancellation, disconnection,
reconnection and restoration. Incoming media still needs actual Host-file inspection
and device capability validation before this path can support import/replacement.
Application artwork-prefix capture is bounded to 512 MiB; larger workloads still
need an appropriate streaming interface rather than unbounded memory use.

Three additional fault injections reproduced successful preparation despite a
corrupted retained thumbnail prefix, moved retained image extent, or duplicate
output thumbnail path. Independent artwork verification now rejects all three.
It compares retained locations and source image sizes against source ArtworkDB,
and retained prefix lengths/hashes against captured file inventory, without trusting
reconciliation's output as the expected value.

An authorized physical test used the matching 544-Track Library to replace one
cover and remove a different Track and its media. The exact issued review saved
four iTHMB files, ArtworkDB, and iTunesDB before removing the media file. Read-back
matched every candidate artifact and confirmed the removal. Storage then restored
the entire transaction: all 26 captured original file contents matched their prior
sizes and SHA-256 hashes, and full flushing succeeded. The resulting Library again
contains the original 544 Tracks. Recovery data is retained. Restored targets have
new filesystem fingerprints, so old captures or an already-open application need
fresh observations before another write. The 20 MB historical database was excluded
from the candidate and retained its original fingerprint. This establishes the
tested application publication/recovery path, not physical firmware behavior.

### Incoming-media inspection follow-up

An application Media Inspector now obtains actual container/stream facts through
FFprobe over a private temporary Host snapshot created by Storage. File size and
SHA-256 bind the observations to captured content. Source changes during copying
fail; edits after capture cannot change the inspected bytes. Later publication must
still verify that hash. The child process is cancelled/reaped on failure and has
bounded output, a deadline, and local single-file input restrictions.

Synthetic real-media fixtures exercise WAV, AIFF, MP3, AAC, ALAC, high-resolution
multichannel FLAC, silent H.264 video, Matroska video, embedded covers, chapters,
multiple audio languages, and both QuickTime `text` and MP4 `tx3g` subtitle sample
entries. The latter share FFprobe's `mov_text` codec name, so codec-only validation
would miss a container distinction. Parser/process fault tests reject invalid
numbers, duplicate identities/fields, mismatched sizes, oversized output, errors
reported with exit code zero, timeouts, and cancellation. Missing facts stay absent.

Initial tests exposed a Windows Python 3.12 difference between path `stat` and
descriptor `fstat` creation/change times. Cross-API identity comparison now uses
the established device/inode/size/modification fields; change-time comparisons stay
within their respective APIs. Cancellation exceptions are also preserved rather
than translated into Storage I/O failures. The focused inspection/capture run
passes 39 tests; the broader Storage/Library/application run passes 698 tests with
one Darwin-only skip.

A read-only connected-device test freshly exported the matching Library's selected
music and Podcast files through Storage and inspected those Host exports. Both
report embedded JPEG artwork as stream zero and audio as stream one. The music is
ALAC and the Podcast AAC LC despite both having `.m4a` paths. All 26 captured device
files retained exact pre-test fingerprints. Existing native bitrate/format values
are not automatically repaired to match the new observations; metadata-only edits
must still preserve unrelated source values. The 20 MB database remains a separate
source and was not used to interpret these media files.

This establishes real-media inspection, not device compatibility or completed
import/replacement. Device policy, conversion, gapless/native codec mapping,
incoming-file transaction composition, drafting/UI integration, non-stream document
media, and full firmware verification remain required.

The comparison also identified a native-mapping concern for incoming audiobooks:
Original iOpenPod chooses the Audible-style format flag from the `.m4b` suffix,
which cannot establish that the actual codec is Audible. [libgpod's Track field
documentation](https://raw.githubusercontent.com/fadingred/libgpod/master/src/itdb.h)
distinguishes AAC from Audible for that flag and describes MP3 gapless data as a
specific frame-byte interval, not whole-file size. These rules need codec fixtures
and independent checks before generating new native media facts; retained source
diagnostics are not a substitute.

### Prepared media content follow-up

The user clarified that current work is backend readiness, without implementing
the Sync engine or transcoder. The Library API previously rejected silent video
and document records because every supplied media resource required positive audio
timing. Three public preparation regressions reproduced that rejection.

`PreparedMedia.content` now explicitly distinguishes audio, video, audio/video, and
documents independently of Library classification. Existing callers default to
audio. Silent video can have zero audio rate; document records can have zero
duration and audio rate. Contradictory audio timing and gapless facts are rejected.
Reparsed replacement output clears both sample-rate representations, retains Track
identity, and remains editable without supplying the media resource again.

The new regression file passes 17 cases, including a generated silent-video
fixture and caller-owned document identities. The existing 15-classification
lifecycle cases now use document timing for PDF/EPUB. This is database-contract
coverage, not document inspection or firmware compatibility. No device files were
written during this follow-up.

### Native Track header follow-up

Corruption tests found that preparation accepted changes to six native fields
across metadata edits, additions, and replacements: the low fixed-point sample-rate
bits, unknown media-type bits, video flags, played/advisory representations, and an
opaque header value. Eighteen cases passed verification incorrectly. Additional
cases reproduced acceptance of altered unmodeled header bytes and changed signed
zero or NaN payload encodings. Semantic equality and lossless candidate reparse did
not establish preservation of the source.

Native verification now derives defined field expectations from retained source
values, shared Chunk Definition defaults, and permitted semantic dependencies.
It checks header gaps and future extension bytes independently, as well as exact
retained float encodings. Identity, codec-resource, artwork, and browse-group
relationships retain their dedicated checks. Noncanonical source values survive
unrelated metadata edits; they are not normalized to make verification pass.

Twelve practical sort-edit tests also reproduced an actual writer error: replacing
or clearing any of the six sort overrides replaced the whole indicator byte,
discarding its other bits. The Original writer documents bit zero as presence and
bit seven as a collation flag. The new writer now changes only bit zero, preserving
all other source bits and both trailing bytes. Independent verification enforces
that rule. The native regression file now passes 63 cases.

Read-only tests loaded the matching connected iPod's iTunesDB and ArtworkDB, prepared
all six sort overrides through set/clear operations, and prepared an album rename.
All 26 captured device files retained their complete fingerprints. A separate
standalone comment edit passed on the historical 6,541-Track database without
assuming matching media or artwork. Candidates stayed in Host memory and used a
synthetic signing identity; these tests did not publish files or exercise firmware.

### Secondary video flag follow-up

Captured headers contain matching primary/secondary video flags: all 544 active
Tracks are `(0, 0)`; the historical source has 6,266 `(0, 0)` pairs and 275 `(1, 1)`
pairs. Original iOpenPod's `mhit_writer.py` writes both from the derived movie flag.
The new writer updated only the primary flag. Nine public preparation regressions
reproduced unset mirrors on video additions and stale mirrors when changing
between audio and video classifications.

The writer and independent verifier now update/require the secondary flag when
the shared definition says it fits the source header. Short headers retain their
extent, and unrelated metadata edits preserve noncanonical source pairs. Twenty
tests cover the five video classifications, ordinary audio, both reclassification
directions, older header lengths and the exact field boundary, unchanged source
mismatches, changed video categories, and injected stale output mirrors.

A read-only connected-source test inspected generated H.264 and AAC fixtures and
prepared a silent-video addition, a metadata edit, replacement by audio, and removal
of that added Track. The native flag pairs changed from `(1, 1)` to `(0, 0)`, and
the final candidate retained the original 544 Tracks and unchanged ArtworkDB.
A separate comment edit on a historical video preserved its `(1, 1)` pair without
assuming matching media/artwork. All 26 connected device-file fingerprints remained
unchanged; the planned fixture paths were never created on the device. Candidates
remained in Host memory with synthetic signing, without enabling application import
or Sync.

### Unchanged-draft resource validation follow-up

An unchanged draft returned retained database bytes before checking supplied
resources. Twelve failing regressions demonstrated acceptance of unrequested media,
duplicate identities or paths, invalid inventory, and source bytes that disagreed
with their captured fingerprint. The same invalid inputs already blocked metadata
edits. Resource validation now runs before the unchanged-draft return and appears
in the reported stages and timings. Errors withhold output and include their record
context in DEBUG logs. Caller cancellation still propagates without changing the
source or draft.

Valid captured context remains accepted, and no-op output stays byte-exact without
reconciliation or signing, including unsupported source/target signature schemes.
The focused resource regression file covers 32 cases. Read-only connected-source
checks confirmed both iTunesDB and ArtworkDB preservation and rejection of invalid
resources. A separate no-op on the historical 20 MB database supplied no media or
ArtworkDB from the connected iPod. All 26 connected file fingerprints remained
unchanged.

Supplying `PreparedMedia` alone does not request replacement; preparation now rejects
it consistently instead of silently ignoring it. The explicit replacement
follow-up below addresses content changes whose projected metadata stays identical.

### Explicit media replacement follow-up

Library Drafts now carry a keyword-only `replace_media` tuple of retained source
Track IDs. Analysis validates these identities, reports each replacement and its
Write Effect, and requires Prepared Media even for an equal snapshot. Preparation
recomputes the requirements and consumes the codec facts instead of retaining the
unchanged Track Chunk without inspecting them. Existing native verification checks
the reparsed output independently. Captured replacement dependencies are returned
even when the database bytes also stay unchanged.

Public API regressions cover unchanged metadata and codec facts, combined edits,
invalid identities, stale sources, forged plan summaries, missing or contradictory
resources, unsupported signatures, short headers, retained native values, and
injected corruption of each supplied codec field. Complete source-byte recovery
after restoring just the changed codec fields checks unrelated data preservation.
The source and draft remain unchanged. This adds no application replacement
publication or device mutation. The contract is recorded in ADR-0034.

### Repository checks

Repository checks: `uv lock --check`, Ruff formatting/lint, Mypy, and Rumdl pass.
The focused Library/application run passes all 452 tests. The full suite reports
798 passed, one platform skip, and one unrelated GUI failure:
`test_player_idle_state_compacts_and_animates_to_active_height` expects a 56-pixel
idle surface but receives 64. That failure also reproduces from an extracted
unchanged `HEAD` baseline; the test and Player imports were confirmed to resolve
inside the baseline. No player layout code was changed in this investigation.

The follow-up full suite reports 848 passed, one platform skip, and the same
existing player-height failure (238 seconds). A final preservation refinement for
an unchanged native NaN sample rate then passed all 51 focused native-verification,
media-lifecycle, and occurrence tests. Ruff formatting/lint, Mypy (328 files),
Rumdl, and the lock check pass. This does not make the full suite green; the
independently reproduced GUI failure remains outside this change.

After the Storage Transaction implementation, the full suite reports 906 passed,
one platform skip, and the same existing player-height failure (207 seconds). The
only subsequent change was adding same-size Host-input corruption coverage; the
final focused Storage run passes 138 tests with one platform skip. Static checks
pass across 332 source files and 56 Markdown files.

After application resource integration and independent artwork corruption checks,
the focused Library/application suite passes 521 tests. The full suite reports
926 passed, one Darwin-only skip, and the same existing player-height failure
(269 seconds). No other test fails. Final Ruff formatting/lint, Mypy (335 files),
Rumdl (57 files), UV lock validation, and diff checks pass.

After real Host media inspection, the full suite reports 965 passed, one Darwin-only
skip, and the same existing player-height failure (292 seconds). The focused
Storage/Library/application suite passes 698 tests with one platform skip. Final
Ruff formatting/lint, Mypy (343 files), Rumdl (59 files), UV lock validation, and
diff checks pass.

After the media-content follow-up, the focused Library/application/Storage suite
passes 715 tests with one Darwin-only skip (39 seconds). Ruff formatting/lint,
Mypy (344 files), Rumdl (59 files), UV lock validation, and diff checks pass. The
full suite was not repeated for this focused backend change; its latest result is
the inspection run above, including the known unrelated GUI failure.

After native header verification and sort-bit preservation, the full suite reports
1,015 passed, one Darwin-only skip, and the same independently confirmed unrelated
player-height failure (225 seconds). The native regression file passes 63 cases.
Ruff formatting/lint, Mypy (345 files), Rumdl (59 files), UV lock validation, and
diff checks pass. Final read-only connected-source checks prepared all 14 candidates
and verified 26 unchanged device-file fingerprints after the float-encoding checks
were added.

After the secondary video mirror fix, the focused Library/application/Storage suite
passes 768 tests with one Darwin-only skip (40 seconds). Ruff formatting/lint,
Mypy (346 files), Rumdl (59 files), UV lock validation, and diff checks pass. The full
suite was not repeated for this focused change; its latest result remains the
1,015-pass run above with the known unrelated GUI height failure.

Tests use the real public preparation path, reparse native output, and inject
malformed output before independent verification. Fixed Original writer fixtures
provide additional format evidence. Passing these tests does not resolve the
documented grouping-policy differences or establish physical firmware compatibility.

After unchanged-draft resource validation, the focused Library/application/Storage
suite passes 800 tests with one Darwin-only skip (43 seconds). Ruff formatting/lint,
Mypy (347 files), Rumdl (59 files), UV lock validation, and diff checks pass. The full
suite was not repeated for this change; the known unrelated GUI height failure
remains recorded above.

After explicit media replacement, all 28 new public API regressions pass. The full
suite reports 1,222 passed, one Darwin-only skip, and the same documented unrelated
player-height failure (331 seconds): the idle surface measures 64 pixels instead
of 56. Ruff formatting/lint, Mypy (360 files), Rumdl (63 files), UV lock validation,
and diff checks pass. This increment used in-memory database fixtures and performed
no device mutations.
