# ADR-0019: Project databases through a common Library contract

- Status: Accepted
- Date: 2026-09-05

## Context

Application models exposed iTunesDB flags and a Library Snapshot carried lossless
Database Documents and an Artwork Index. The Application Layer translated MHIT and
MHOD records itself. Future Library Sources such as Plex or Jellyfin would therefore
need to fabricate database values to use the existing GUI.

## Decision

`iPodDB.library` owns a public, immutable Library Snapshot and Track contract with
semantic enums, boolean flags, and explicit units. Other sources construct the same
records directly. iPod-specific diagnostic values remain in optional typed iPod
Track Details, rather than an untyped extension dictionary.

The `IPodLibrary` source adapter translates iTunesDB and ArtworkDB through the
existing parsers and definitions. It retains lossless documents privately and
publishes only its snapshot into Active iPod state. Its artwork interface selects a
cover and returns an explicit file-range read plan. iOpenPod owns Storage access,
connection validation, scheduling, and caching; iPodDB decodes caller-supplied bytes.

This changes the Library Snapshot ownership described in ADR-0012 and narrows the
application consumer described in ADR-0008. Their lazy-loading and single lossless
writer-path requirements still apply. Database Documents remain the authoritative
representation for serialization; a Library Snapshot is not a second writer model.

The common types live in iPodDB because it is the existing data boundary consumed
by iOpenPod. They do not import binary definitions, Qt, Storage, or iOpenPod. A fifth
shared package and a general plugin framework are unnecessary for this contract.

## Consequences

All current GUI and application model consumers use one contract. Format constants,
Chunk traversal, timestamp conversion, FourCC interpretation, and artwork linking
are confined to iPodDB. Optional diagnostic columns show missing values for Tracks
that have no iPod Track Details.

Numeric Track and artwork IDs are opaque within a Library Snapshot. Future sources
map their native identities to these IDs and retain transport credentials, URLs,
and lookup state in their adapters. Combining simultaneous Library Sources requires
an explicit identity policy; it is not implied by this change.
Snapshot construction rejects duplicate Track IDs so display and playback lookups
cannot resolve the same identity to different media. This validation does not alter
the lower-level lossless parser's ability to retain those records.

Constructing or replacing a snapshot does not mutate retained database bytes.
Source connectors and semantic-to-database editing or construction workflows remain
separate work. Unchanged serialization must still preserve every unknown byte.
