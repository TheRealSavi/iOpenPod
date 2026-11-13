# ADR-0257: Continue writes after browse ID conflicts

- Status: Accepted
- Date: 2026-11-12
- Amends: ADR-0165, ADR-0172, ADR-0253, ADR-0254, ADR-0255, and ADR-0256

Album and artist ID selection must let the Library write continue. Keep a
Track's usable existing link while it still fits. Prefer exact Artist and Store
Album evidence for joining Tracks. When several destination records remain
plausible, choose the one with the most surviving members, then the lowest
native ID. Report the choice as a warning.

Allocate a fresh native record and SQL ID when a known release has no matching
destination, a source ID is missing or repeated, or reusing a record would
overwrite another group's metadata. Keep distinct known releases and feeds
separate when creating Albums. Preserve the old records and their Unknown Data.
Ordinary edits that leave browse relationships alone retain their source links.

Podcast normalization also chooses a usable Album or allocates one. Same-titled
shows can retain separate Albums for separate feeds. A name-only duplicate with
conflicting private data remains in the database while Episodes link to the
selected Album. Sort 36 uses a valid representative among the retained records
when possible and otherwise uses the existing Track-number ordering.

Verification checks the chosen or newly allocated links, native record metadata,
and SQL identities before Storage publishes the Library. Regression fixtures
cover ambiguous releases, mixed release batches, invalid native IDs, incompatible
shared records, and retained private Podcast data.
