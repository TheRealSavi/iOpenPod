# ADR-0127: Resolve Sync duplicates with explicit Track associations

- Status: Accepted
- Date: 2026-10-07
- Extends: ADR-0065, ADR-0066, ADR-0070, ADR-0076, and ADR-0120
- Amends: ADR-0066's non-actionable ambiguous correlations through explicit resolution;
  ADR-0065 and ADR-0076's Library-commit prerequisite for association-only Sync

## Context

An Acoustic Fingerprint can identify possible copies of a recording without
establishing the user's desired Library entries. The same recording may belong to
an original Album and a compilation, and existing iPod copies can have different
Playlist memberships, ratings, playback history, and playback positions. Choosing
which Host file controls an iPod Track is separate from choosing which copies to
retain.

The Original iOpenPod baseline at `origin/1.x` groups Host files by fingerprint and
album in `sync/track_identity.py`, silently retains a representative of copies in
the same album, and aliases their Playlist references. Its existing-track matcher
can choose a best metadata score among several candidates. This decision preserves
its recognition of separate albums and established relationships while replacing
silent suppression and arbitrary ambiguous matching with explicit user choices.

## Decision

The immutable Sync Plan exposes **Sync Duplicate Groups** containing the Host and
iPod candidates and any established pairs. Equal Acoustic Fingerprints group
Tracks; exact Image Content Fingerprints group full-resolution Photos. Prior Sync
Details also connect candidates even when Host content has since changed. The group
is matching evidence, not proof that entries are unwanted. Titles and artists alone
do not establish duplicate content. Acoustic analysis retains ADR-0120's first-120-
seconds and audio-only limits; video content and full-file equality remain unknown.

The Host Media Scan continues to deduplicate normalized Host paths across
overlapping folders, explicit files, and approved Playlist references. Each
Playlist occurrence keeps its own identity and position. Separate Host files remain
separate candidates even when their audio and metadata match.

| Case | Automatic behavior | User decision |
| --- | --- | --- |
| One Host file reached through several sources or Playlists | One Host Track, preserving every Playlist occurrence. | None beyond existing external-reference review. |
| Several Host copies and no iPod copy | Display the possible duplicates; retain each as an independent Add candidate. | Select one, several, or no copies. Different albums remain separate entries when both are selected. |
| Several Host copies and one iPod copy with a proven relationship | Keep the established pair and expose additional Host copies as optional Adds. | Add any extra copies wanted. |
| Several Host copies and one iPod copy without a proven relationship | Preserve the existing Track and leave ambiguous Host candidates unresolved. | Choose one Host-to-iPod pair, or explicitly add separate copies; skip the others. |
| One Host copy and several iPod copies | Reuse a proven pair when available and retain every other iPod copy. | Otherwise choose the pair; independently select any extra iPod copies for removal. |
| Several copies on both sides | Preserve established pairs; equal counts never assign the remaining pairs. | Choose each remaining one-to-one pair, Add, or Remove independently. |
| Copies only on the iPod | Keep all copies; removal candidates start unchecked. | Explicitly remove unwanted copies after reviewing their details. |
| Similar names with different content evidence | Keep independent entries. | Ordinary selection; names alone never collapse them. |

A **Sync Duplicate Resolution** names explicit Host-to-iPod pairs, Host files to
Add separately, and iPod identities to Remove. Unmentioned ambiguous Host candidates
are skipped and unmentioned iPod candidates are retained. Known pairs stay fixed in
the resolution; ordinary Sync Selection still controls their desired membership.
Resolution choices must belong to the captured group, remain one-to-one, and cannot
both pair and remove the same iPod item or both pair and add the same Host item.
Resolving one pair does not silently pair the remaining candidates. Unresolved
groups do not block unrelated selected work. A Playlist containing an ambiguous
Host candidate that remains skipped is preserved rather than rewritten with that
occurrence missing, including after an explicit skip resolution. An explicit pair
can supply Playlist mapping even when Review excludes its metadata Update.

An explicit pair becomes an Update with a user-confirmed matching basis, including
when the current metadata is unchanged. It follows the existing validated Sync
workflow so only a successful commit establishes durable Sync Details. Matching
fingerprints retain existing Track payloads, while tags and artwork follow their
independent comparison rules. Existing Track identity and device-owned playback
state survive the association. A future scan reuses the committed Host path
relationship before considering fingerprint candidates. Selection alone, skipped
or failed operations, and cancelled publication never create successful provenance.

If another retained copy previously claimed the same Host path, successful helper
publication retires that competing path hint while retaining its historical facts
and fingerprint. Updates to an existing Track target its Library identity as well
as its Device Path, so another Track sharing the same file does not inherit the
new association.

When an association changes no Library or media bytes, Sync explicitly requests an
unchanged Library review. Preparation still independently verifies the serialized
Library and captures its dependencies; saving rechecks the current source and those
dependencies without creating an empty Storage Transaction or rewriting databases.
The subsequent verified atomic helper publication commits the association. A helper
failure in this case means the association failed, while a helper failure after
actual Library changes retains the existing saved-Library warning policy.

Cleanup is an explicit Remove action. Review exposes source paths, album details,
and existing playback and Playlist information to support the choice. Removing a
Track removes its Playlist occurrences under the ordinary removal contract; it
does not redirect them to another copy or combine ratings, play counts, or playback
positions. Those changes would require a separate consolidation policy. Host files
are unchanged. All device writes retain Storage validation, recoverable removal,
verification, and successful-commit requirements.

## Consequences

Users can retain intentional copies and safely resolve accidental ones without
repeated ambiguity after a successful association. The cost is an explicit choice
when evidence admits several relationships. Review decisions are scoped to the
captured comparison and retired with it; helper loss may require resolving them
again. After actual Library changes, a helper-publication failure remains a warning
about the committed Library and can require the association to be chosen again.
