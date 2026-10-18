# Project native CDB metadata into SQLite

> ADR-0149 adds captured Podcast GUID, container classification, media-mask, and
> short/full description mappings while retaining the category policy below.
> ADR-0150 retains existing firmware schemas, versions, and unrepresented metadata;
> the Original-compatible schemas below are defaults for missing artifacts.

- Status: Accepted
- Date: 2026-10-13
- Amends: ADR-0061's Snapshot-only SQLite generation input

The public Library Snapshot deliberately excludes firmware categories and chapter
Unknown Data. Generating SQLite solely from that projection lost dataset-5 Music
and Audiobooks containers present in Original iOpenPod. iPodDB now supplies typed
native metadata from the same independently checked CDB alongside its Snapshot.
This keeps native firmware state out of the application editing contract without
making SQLite another readable Library authority.

The input retains dataset ownership, category kind and visibility, ordered Track
membership, native smart preferences and rule bodies, container dates, and chapter
bodies. Categories retain CDB membership; they are not reevaluated as user Smart
Playlists. Dataset-5 flags are interpreted in that dataset's context. Container IDs
are unique within SQLite even when native datasets reuse IDs. User Playlist IDs
remain stable for native smart-rule references; generated Master and category IDs
yield to those identities when necessary.

All five schemas and the nine explicit Library indexes match Original iOpenPod
v1.68.1. Generation supplies browse ranks and calculated group metadata without
requiring optional device SQL. Existing album collation, native codec evidence,
device time conversion, and checksum policies remain authoritative when they
provide more precise behavior than Original defaults. Native sample counts take
precedence over the Original duration/rate estimate. Empty Genius tables follow
Original behavior; no recommendation data is invented.

Device postprocessing runs against the in-memory artifact set. Before signing,
generation checks database integrity, Track and container identities, exact ordered
membership including repeated occurrences, and references between companion files
and browse records. Failures become preparation errors and all temporary connections
are closed. Storage continues to publish the complete generation through the
existing recoverable transaction. No-op saves still preserve existing bytes and do
not regenerate SQLite. Physical firmware acceptance is a separate validation step.
