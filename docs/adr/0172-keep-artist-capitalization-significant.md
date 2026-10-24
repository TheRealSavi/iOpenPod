# ADR-0172: Keep artist capitalization significant

- Status: Accepted
- Date: 2026-10-23
- Amends: ADR-0165 for native artist ownership

## Context

The maintainer specifies that the iPod treats differently capitalized artist names
as distinct artists and that iOpenPod must do the same. The native artist writer
already uses exact names, but the common Library's presentation keys folded artist
case, merging those artists and their same-titled Albums in the browser.

Original iOpenPod's `mhli_writer.py` groups artist names case-insensitively. That
baseline behavior does not override the explicit case-sensitive product contract.

A reported `library.ambiguous_group` error is a separate condition: distinct source
artist groups already reference one native artist ID, and a requested membership
change would rewrite their shared record. Generated fixtures reproduce that error
with either case variants or completely different names. Distinct names with
distinct native IDs prepare successfully. These fixtures do not establish how the
reporting user's source acquired its native relationships.

## Decision

- Artist identity uses exact names in native reconciliation and common Library
  presentation. Track text is not normalized implicitly.
- Album presentation keys retain the exact effective Album Artist so same-titled
  Albums owned by case-distinct artists remain separate. Existing album-title
  equivalence and explicit common Album Artist grouping remain unchanged.
- Search remains case-insensitive. User-requested Normalize Tags remains a
  separate, previewed metadata-edit workflow.
- When an artist-name or membership change touches a native artist record shared
  by distinct exact names, reconcile all affected artist groups. The exact name
  matching the source record's label retains its native and SQL IDs. Other names
  receive separate records with newly allocated native and SQL IDs, and their
  Tracks are relinked accordingly. IDs cannot collide with retained identities.
- Clone the shared source record for each new artist, changing only its identities
  and artist text. Preserve private header bytes and child records. Retain the
  source record unchanged even when its label matches no remaining group; such
  unreferenced records are already preserved by the Library writer.
- Missing records, repeated native IDs, or multiple candidate source records still
  block affected preparation because they do not identify one record to preserve
  and clone. The shared-album guard from ADR-0165 remains unchanged. No-op writes
  and unrelated edits preserve existing artist relationships.
- Header requirements include all affected artist groups. Independent verification
  checks exact labels, distinct group references, retained identities, and fresh
  nonzero SQL IDs, including collisions with other newly created records.

## Validation

Model tests cover separate Artists and Albums, exact collection filtering, and
case-insensitive search. Public preparation tests cover adding case variants,
case-only artist splits, additions to shared records, simultaneous renames, exact
name merges, deletion, Track-order independence, and missing or repeated source
records. Fixtures include private header bytes and opaque children and compare
retained source rows byte-for-byte. Fault injection checks shared references,
incorrect native IDs, SQL collisions, and wrong labels. Unrelated edits and no-op
writes continue to preserve existing source relationships.
