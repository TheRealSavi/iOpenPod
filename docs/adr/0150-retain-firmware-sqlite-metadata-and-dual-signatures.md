# ADR-0150: Retain firmware SQLite metadata and dual signatures

- Status: Accepted
- Date: 2026-10-18
- Amends: ADR-0061, ADR-0100, ADR-0141, and ADR-0147

## Evidence

A Finder-accepted Nano 5 capture has valid HASH58 and HASH72 signatures under
scheme 1. After Play Counts ingestion, iOpenPod retained a stale HASH58, switched
to scheme 2, replaced SQLite version/schema information, and erased SQLite-only
lyrics and store metadata. Its date projection also imported the Core Data
reference epoch as actual playback history. See the
[capture comparison](../research/finder-playcounts-compatibility-2026-10-18.md).
These are evidenced discrepancies; they do not independently establish the cause
of Finder rejection.

## Decision

Changed HASH72 iTunesDB/iTunesCDB output uses scheme 1 and receives both a fresh
HASH72 and HASH58 over the final physical bytes. Preparation verifies both. The
selected device's FireWire GUID is therefore required alongside HashInfo material.
Locations Checksum Books keep their separately selected signature format. Ordinary
no-op serialization continues to preserve the source bytes exactly.

iTunesCDB remains the sole semantic Library read authority. For a SQLite-changing
save, the Application Layer captures existing companion bytes through Storage and
binds their fingerprints to the Review. iPodDB merges the independently checked
CDB projection into in-memory copies of those companions. This supersedes the
policy of deliberately discarding SQLite-only metadata on every refresh.

- Retain existing `version_info` rows, firmware schemas, indexes, unknown tables,
  and unknown columns. Do not migrate a captured schema to the generator's version.
  Missing artifacts use the built-in schema; their initial minor version follows
  the checked CDB version. SQLite's own file bookkeeping is not an application
  version and may change during writes.
- CDB-owned Track metadata, playback history, identities, membership, locations,
  browse ranks, and calculated values remain authoritative. SQLite database and
  Master container IDs and Master dates use their corresponding native fields.
  `has_been_played` includes the native played state independently of completed
  play counts.
- Preserve unrepresented store, Genius, rental, video-file, UI, and supplemental
  metadata. SQLite-only lyrics and chapters survive until explicitly replaced or
  cleared. Known per-Track rows are removed when their Track is deleted; file-bound
  supplemental facts are invalidated when media is replaced. New authored chapter
  or lyrics data takes precedence.
- Match unknown browse-row metadata through surviving Track membership because
  generated browse IDs can be reused for different groups. Splits and merges have
  no single predecessor and receive fresh defaults. Unknown tables remain opaque;
  their internal references cannot be inferred or repaired.
- Source triggers do not execute while applying the checked projection. Row merges
  preserve unowned values and source defaults; replacing the complete known table
  contents avoids transient conflicts when unique values swap. Source schemas are
  retained without executing their SQL as a creation script.
- Reject unreadable or incompatible present companions before publication instead
  of silently erasing them. The four calculated columns absent in the captured
  Nano 5 schemas are optional. Missing known tables can be created from trusted
  built-in definitions. Selection without a pending save still reads the CDB.

Validate the resulting complete artifact set and sign its resulting Locations
bytes. Storage still publishes one recoverable generation; iPodDB receives bytes
and never device paths. Capturing companion contents adds preparation memory and
read cost beyond fingerprint-only capture.

For binary Play Counts only, the exact raw date equal to the Mac epoch offset plus
the Core Data epoch offset plus the captured database UTC offset means no new date.
Test this before geographic timezone conversion; historical DST can otherwise
introduce a one-hour error. Preserve any earlier history and retain every other
real date, even with zero completed plays. This rule is inferred from paired
captures, not an Apple specification for all firmware. It does not normalize
ordinary Track dates, plist dates, or previously committed erroneous history.

## Verification limits

Regression tests cover dual signing, retained schemas/versions, edits/deletions,
supplemental metadata, changed group order, media replacement, and virtual Storage
publication. Host-only replays retain the captured versions, schemas, store rows,
and lyrics while eliminating the false playback dates. Physical Finder acceptance
remains a separate experiment. Podcast artwork, chapters, advisory flags, Episode
and season numbers, and intentional dataset-5 containers remain supported.
