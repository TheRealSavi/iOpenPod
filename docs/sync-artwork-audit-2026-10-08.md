# Artwork Sync lifecycle audit — 2026-10-08

## Outcome and evidence

The reported incident has no supplied before/after database or log, so its exact
cause is not established. This audit reproduced multiple independent failures
that can remove or hide covers and added repairs through the existing boundaries.
It did not modify a physical iPod. Tests use synthetic libraries, virtual volumes,
and read-only local Nano 5 and Nano 7 captures.

The [research report](research/artwork-sync-loss-2026-10-08.md) covers more than
twenty primary artifacts from more than a dozen source families. It distinguishes
independent implementations from libgpod wrappers and iOpenPod-derived projects.
The Original iOpenPod baseline was inspected at local `origin/1.x`,
`a20242428b93b672d14b37230772dbad75139c69`; it is not a runtime dependency.

## Pipeline examined

| Stage | Main implementation | What establishes preservation |
| --- | --- | --- |
| Device selection | `device_coordinator.py`, `IPodLibrary.with_artwork` | Captured database fingerprints, retained source bytes, independently bounded recovery. |
| Host artwork discovery | `host_media_library.py` | Embedded/folder source facts, image validation, unavailable observations distinct from confirmed absence. |
| Change detection | `sync_plan.py`, `sync_track_details.py` | Host/iPod cover provenance and the reviewed artwork-change flag. |
| Sync draft and cover preparation | `sync_execution.py`, `media/sync_artwork.py`, `sync_artwork_fallback.py` | Existing associations survive media-only changes; unavailable covers remain retryable. |
| Artifact preparation | `library/_artwork_writing.py`, ArtworkDB builder/writer, iTHMB codecs | Native identities, shared owners, format layouts, source prefix fingerprints, fresh allocation and preserved Unknown Data. |
| Verification | `_artwork_verification.py`, `_write_verification.py`, `_write_preparation.py` | Reparse, native metadata, target representations, bounds, retained pixels and independently derived repair bytes. |
| Late-device companions | `SQLiteDB/database.py` | Projected artwork ID reaches item cache ID and covered album Track selection. |
| Publication | `library_resources.py`, `device_coordinator.py`, Storage transactions | Thumbnail files precede ArtworkDB and primary Library publication; dependencies and outputs are verified. |
| Commit and reload | Storage recovery, Sync helper publication, coordinator adoption | Cleanup verifies unconfirmed durability before discarding originals; successful adoption clears pending repairs. |

## Reproduced findings and corrections

### Failed Host-cover observations became removal requests

Unreadable covers, invalid or partially downloaded images, and directory-entry
observation errors became `artwork=None`. With changed media facts, the planner
treated that absence as removal. Real scan-to-Sync tests reproduced cover identity
100 becoming zero through Storage publication. A shared folder cover can expose
every Track in an Album to this failure.

The scanner now reports unavailable cover evidence, tries valid alternate cover
files, and prevents failed observations from requesting removal. Independent media
changes continue. Later scans retry the source and can successfully publish its
cover. A readable, intentionally absent cover still follows the existing removal
policy.

The same loss reproduced with malformed embedded APIC image bytes: a successful
scan and Sync cleared the saved cover because failed decoding appeared to prove
absence. Embedded observations now carry availability separately from pixels.
Malformed present image payloads and failed tag reads cannot authorize removal;
valid alternate embedded images or folder covers remain usable. The Host cache
records this distinction and rechecks old cached no-cover observations once.

### Payload replacement ignored reviewed artwork intent

The payload-replacement draft assigned zero when the Host Track had no cover,
even if the reviewed item had `artwork_changed=False`. The full Sync regression
reproduced loss of the retained association. Draft construction now honors the
reviewed flag, including preservation of embedded covers during unrelated Rockbox
tag updates.

### Wrong image-list counts hid complete artwork records

An MHLI undercount made valid MHII records opaque trailing bytes; a later writer
could preserve those bytes while still emitting an incorrect count. An overcount
could cross the dataset boundary and make optional ArtworkDB loading fail.
First-hand nano experiments independently report whole-library artwork rejection
from a wrong image count; see the linked research for the limits of that evidence.

The recovery API derives the count only from complete, contiguous records filling
the declared image dataset. The existing parser validates them. The Library view
recovers covers immediately, while unchanged serialization preserves original
bytes. Preparation produces an explicit repair. Repair-only Sync is reachable
from Review; it changes the count without rewriting iTunesDB or thumbnail files.
Tests also cover cancellation, concurrent source changes, restoration of the exact
damaged original, and idempotence. A serializer fault that changes unrelated root
data is rejected against the independently patched original.

### Valid retained allocations were rejected

libgpod and ipod-sharp leave the optional secondary MHNI size zero. foo_dop can
record a padded allocation larger than the raster. Previously both could trigger
cover deferral, especially with F1061's retained-layout checks.

Validation now treats zero as no separate allocation declaration and accepts
bounded padding after a known raster. Allocations still must contain the raster,
fit fingerprinted files and pass overlap checks. Known F1061 raster sizes remain
6,160 and 6,272 bytes. Existing header values and pixels remain unchanged.

### Damaged old thumbnail files prevented replacement from good Host pixels

Missing and truncated iTHMB files previously caused cover deferral even when the
request supplied fresh pixels for every owner of the damaged image. Preparation
now regenerates those covers under new image identities, reserving damaged and
unreadable filenames against writes. Old MHII records, Unknown Data and surviving
file bytes remain. A bounded unreadable-file path also permits this through actual
Sync when all originally covered surviving Tracks receive fresh assets and the
Filesystem Session remains active.

Healthy retained representations still establish layout requirements. If any live
Track retains the damaged image, this recovery cannot ignore its missing pixels.
Tests cover all-owner regeneration, partial shared-owner refusal, missing and
truncated files, read errors, F1061 layout selection, and filenames belonging to
representations excluded from the display index. Verification independently
rejects writes into unavailable or incomplete old allocations.

Later Syncs can continue past the retained damaged orphan records once no original
or desired Track references them and no reverse owner remains. Healthy historical
records remain layout evidence. A second-Sync regression verifies that a different
Track can keep its first regenerated cover while another receives a new cover.

### Native source-cover count and association precedence were wrong

The writer counted generated MHNI representations in MHIT `artwork_count`.
Independent libgpod and foo_dop code establishes count one for a newly assigned
single source cover. The writer and independent verifier now apply that rule;
catalog-wide tests exercise devices with several representations.

The read projection also gave a reverse MHII owner priority over a valid explicit
Track link. A stale old reverse owner could select the wrong image, including for
SQLite output. Valid direct links now take precedence, with reverse ownership as
the fallback when a direct link is unavailable. Both original native fields remain
retained on read.

### One invalid representation could hide unrelated covers

A zero format ID raised while building the whole Artwork Index. It now omits only
that unsafe display location, logging its offset, and retains the full original
record and image identity. Other valid representations and independent covers
remain available. This is localized display recovery, not permission to discard
malformed source data during edits.

### Recursive RGB555 was implemented as ordinary row-major pixels

Both encoder and decoder shared the same mistake, so self-round-trip tests passed.
Independent libgpod evidence establishes recursive quadrant ordering. Both paths
now implement that ordering, with independent 4-by-4 vectors and layout guards.
No current static Device Profile selects this encoding, so it is not claimed as
the likely cause of this report.

### Unconfirmed durability could authorize deletion of recovery copies

Ordinary Storage execution accumulated failed flush results but still recorded
COMMITTED. After reconnecting, automatic terminal cleanup could delete the
originals despite uncertain persistence of the published files. Restoration had
the analogous terminal-state problem.

The journal now records whether content crossed a successful durability barrier.
Ordinary publication retains its flush-warning behavior: making Volume-wide
flushes mandatory would block unelevated Windows users. Before cleaning an
unconfirmed or legacy terminal transaction, Storage requires a successful flush
and freshly verifies its recorded result and dependencies. Missing or changed
outputs keep the originals. Confirmed transactions retain the existing cleanup
path. Failure injection covers execution, restoration, reconnecting and retry.
See [ADR-0134](adr/0134-verify-unconfirmed-durability-before-recovery-cleanup.md).

## Validation and limits

Regressions first reproduced the named failures, then passed after their fixes.
They exercise actual Sync planning, preparation and Storage publication in
addition to byte-level format tests. The Nano 5 capture has 51 Tracks and one image;
the Nano 7 capture has 832 Tracks and 247 images. Both remain byte-exact on read and
serialization. In-memory undercount and overcount variants recover the original
projection and prepare exactly the original ArtworkDB without modifying their
compressed iTunesDB or thumbnail files. The captures themselves were not changed.

The final Storage, Application service, Sync execution, regeneration and embedded
availability integration run passed **745 tests**, with five platform-specific
skips. Lock validation, Ruff lint, Mypy (895 source files), and Rumdl pass. Ruff's
format check reports one existing issue in untouched
`tests/iOpenPod/GUI/test_media_tools_settings.py:143`.

German and Spanish catalogs include all five new artwork messages and their
compiled outputs. Their focused checks passed 39 tests; the two remaining
source-coverage failures identify five unrelated deletion-workflow messages
already present at HEAD. Those baseline omissions remain outside this change.
The Application Library boundary check also fails on four existing imports of
`iPodDB.shared.photo_image`, independently confirmed at HEAD. This audit did not
add those imports or change that contract.

Broader testing caught and resolved a metadata-cache reuse regression for
FFprobe-supported media whose embedded artwork cannot be inspected. The related
scanner, metadata, availability and import suites pass 142 tests; import tests
now assert the researched single-cover count while still decoding every required
representation.

The whole-repository run completed with 5,323 passed, six failed and five skipped.
After correcting its three task-related failures, rerunning all six left only the
three baseline failures described above. That broad run began before the final
Storage durability revision; the separate 745-pass integration run exercised the
final revision, including its new recovery checks.

Remaining uncertainty is explicit:

- No regression identifies which failure affected the reporter without that
  incident's artifacts and device details. Physical firmware validation remains
  separate from successful software tests.
- Count recovery does not guess around opaque dataset tails, duplicate identities,
  truncated MHII records or invalid lengths. Such bytes remain evidence.
- Sparse reference-count metadata at MHII offsets 0x38/0x3C varies across writers.
  Its zero value alone is not established corruption; blanket rewriting would be
  unjustified.
- Missing pixels cannot be recreated from metadata alone. Recovery needs a valid
  Host cover, surviving representation, retained original or Backup Snapshot.
- Regeneration currently consumes fresh pixels requested by Sync or a Library
  draft. It does not proactively discover broken device ranges when unchanged
  Host evidence produces no cover edit, or synthesize replacements from other
  thumbnail sizes. Unreadable capture recovery requires replacement assets for
  every originally covered surviving Track; missing/truncated readable inventory
  can establish the narrower affected-image recovery described above.
- A readable Host file with no cover can still request removal after changed file
  facts under the existing Sync policy. Missing historical provenance does not
  independently prove the user intended to keep device-only artwork.
- Storage restoration continues to protect current files matching neither recorded
  version. It retains the recovery evidence instead of automatically overwriting
  a possible unrelated edit.

The governing artwork preservation and repair policy is recorded in
[ADR-0133](adr/0133-recover-evidenced-artwork-without-clearing-unavailable-covers.md).

## Photo pipeline follow-up

The Photo audit confirmed a separate allocation bug: Sync assigned each Photo a
new shard for every thumbnail format, while resource validation required each
representation to occupy an entire fresh file. Allocation now packs successful
Photos into shared per-format shards after final Host-source filtering, including
appending on later Syncs. Rollover happens before a frame would exceed the
configured capacity; the default is decimal 256,000,000 bytes.

Retained candidates are selected using raw MHNI raster/allocation extents, with
case-equivalent references combined. Partial overlaps, invalid ranges, ambiguous
names, missing bytes, and unreadable files reserve their names and cause fresh
allocation. Extension preserves the entire captured prefix, including unknown
tails and unused ranges. Shared buffers are hashed once per resource validation,
each representation is decoded from its own range, and Storage publishes each
physical output only once with its original fingerprint or an absence condition.
Preparation and packing use the same bounded Host workspace.

The bounded MHLI count scanner is now shared by nominal ArtworkDB and PhotosDB
repair APIs, retaining their separate contextual parsers. Photos hidden by a wrong
count become visible; original source bytes remain exact until verified repair
publication. Malformed thumbnail padding no longer hides another usable
representation. Photo-only repair can execute through Sync without unrelated
media changes. The album-art MHIT count rule is not applied to Photo MHII records.

Complete replacements can proceed when an obsolete thumbnail is unreadable or
has an unrecognized filename: that old file is left untouched and reported. This
decision is based on all old owners of a shared path, so removal/replacement order
cannot change the outcome. Surviving shared owners prevent whole-file cleanup.

Regressions cover real Sync append and rollover, memory and disk staging, stale
prefix rejection, cancellation, disconnect, count-only repair, shared-owner
cleanup, malformed references, and rollback after both appended shards and
PhotosDB have been published. The
[Photo research](research/photo-sharding-2026-10-08.md) records independent primary
evidence and the distinction between a compatibility limit and a firmware maximum.
[ADR-0135](adr/0135-pack-photos-into-bounded-shared-shards.md) amends the earlier
fresh-shard policy; full-resolution originals remain separate files.

The final combined database, artwork, Photo media, Application service, Sync,
controller, and Sync Review run passes **1,238 tests**. Its one warning is Pillow's
expected large-image warning in the existing oversized-Photo regression. Mypy
passes 911 source files; Ruff lint, Rumdl, lock validation, and diff checks pass.
The existing unrelated formatting issue and four private Photo helper imports
reported above remain the only failures in the separately rerun formatting and
Application Library boundary checks. No physical-device publication was performed.
