# ADR-0153: Normalize SQLite Podcast Sync from Nano 5 evidence

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0141, ADR-0147, ADR-0150, and ADR-0152

## Evidence and decision

The supplied Nano 5 12.6 baseline and subsequent iOpenPod capture expose the same
Podcast relationship problems addressed by ADR-0152 on Classic, plus SQLite album
splitting, classification, UI-order, and partial-playback differences. Sync now
submits explicit Podcast normalization for SQLite targets too. iPodDB selects the
SQLite traversal policy from the caller's Write Target; it does not infer a model
from database versions or filenames. Ordinary lossless no-op preparation is unchanged.

The shared policy repairs one native album per unambiguous show, representative
Track backlinks, root secondary references, persistent group identities, opaque
group creation seeds, Release Date sort 24, phase bits `0x10B`, and positions equal
to row IDs. It also removes unreferenced artist stubs only when they contain no
metadata or private bytes. Conflicting album data still blocks publication.

## SQLite-specific policy

- Episode rows within each show store ascending publication dates. Equal dates
  retain their requested order and undated Episodes follow dated ones. The special
  Podcasts container uses `play_order=40, is_reversed=1`; the Master uses the
  captured `7,0` defaults. Explicit normalization overrides those two UI columns
  after retention, while other UI fields and ordinary user Playlist choices survive.
- Native sort-36 and standard Master indexes are optional on SQLite targets.
  Existing indexes remain maintained, but missing ones are not invented. A
  dataset-3-only input remains valid without synthesizing dataset 2. Established
  flat counterparts survive and continue to agree with grouped Episode rows.
- SQLite Podcast albums use kind 3 and group by show title and feed identity,
  independently of optional show, album-artist, guest-artist, or season tags. A
  missing feed joins only an unambiguous feed for that title. Different populated
  feeds remain separate in standalone SQLite projection; explicit native show
  normalization continues to reject ambiguous same-title feed relationships.
  Ordinary music albums retain their existing grouping and kind 2.
- During explicit Podcast normalization, empty dataset-5 category templates are
  omitted from SQLite containers, matching the supplied baseline. Their native
  records survive; populated categories and empty user Playlists are retained.
  Other projection requests continue ADR-0141's complete category policy.
- A nonzero native bookmark is evidence for SQLite `has_been_played`, independently
  of completed play counts. This does not mark an Episode listened in the semantic
  Library or change its completed counts, native playback flags, or Listening History.

## Preservation and verification

ADR-0150 still owns schema, version, supplemental metadata, and dual-signature
retention. Native Track metadata, private bytes, purchase flags, existing timed
artwork, chapters, and media are preserved unless explicitly edited. The baseline
is a relationship reference, not a source of literal identities or opaque bytes.
Already-lost private data in the altered input cannot be reconstructed safely.
Valid extra native counterparts and indexes are not deleted to imitate file shape.

Regression tests exercise both native starting shapes, new Episodes and shows,
repeat preparation, optional tags, separate feeds and music, private artist data,
UI retention, categories, and partial playback. Production Sync also runs against
private copies of both supplied captures with an existing-show addition, a new
show, and a second Sync. Checks compare native and SQLite ownership, row order,
source hashes, retained media/metadata/artwork, schemas, versions, and signatures.
These establish serialized structure and transaction behavior. Physical Nano
firmware and Finder acceptance require device testing.
