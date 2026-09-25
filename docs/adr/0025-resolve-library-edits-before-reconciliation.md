# ADR-0025: Resolve Library edits before reconciliation

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0021, ADR-0023, and ADR-0024

## Context

The desired snapshot is a useful submission interface, but analysis previously
reported only its direct differences. Preparation could generate visible Podcasts
membership and native relationships afterward. Field ownership, dependency checks,
and generated values were spread across reconciliation and verification. An index
verification check also accepted an incorrectly sorted permutation.

## Decision

Keep retained Database Documents authoritative and keep the source-bound Library
Draft as the only editable submission. Its snapshot specifies caller-owned choices;
copied diagnostic and derived fields retain their original values. The semantic
field policy explicitly classifies editable, prepared-media, artwork-selection,
derived, retained, identity, membership, and collection fields. Analysis blocks if
a model field lacks a policy. Changed fields use precise dotted paths.

Resolve semantic decisions before modifying a candidate document. The private
immutable Resolved Write contains the effective snapshot, native Track/Playlist
identity assignments, dataset impact, folder aggregates and child rules, playlist
preorder, podcast-group impact, browse-index values, and artwork ownership impact.
Reconciliation consumes these decisions. Shared tree replacement is independent of
the domain passes; those passes do not import the main reconciler.

The public Library Write Plan retains requested changes and exposes a read-only
Library Resolution: generated semantic changes, Write Effects with references to
their requested causes, and preservation constraints. It contains common values,
never source Chunks. Asset encoding, file allocation, and other resource-dependent
native values remain preparation work within the declared effects; exact resulting
bytes, ranges, and allocated identities belong to the Prepared Library. A blocked
draft may have no resolution when its graph or values cannot be derived safely.

Preparation resolves the original draft again. Replacing a public plan's issues,
requirements, effects, or resolved snapshot cannot grant write authority. Resolved
values and generated membership never mutate the submitted draft or loaded source.
Applying Smart Playlist rules and matching entries remains one application edit;
resolution does not reevaluate unrelated Smart Playlists.

Verification checks reparsed artifacts independently of calculated index output.
It checks stable browse ordering, alphabetical group labels and boundaries, and
required indexes on new or structurally edited Masters. Retaining the same index
bytes is insufficient when their input values changed. Safe unrelated source
inconsistencies remain preserved.

Native Track verification additionally compares defined header fields against
their retained source values and permitted semantic changes, using shared Chunk
Definitions for offsets and defaults. Projection alone cannot prove native flag,
unknown-bit, or floating-point encoding preservation. Unmodeled header ranges and
unchanged floating-point encodings are checked as bytes. Updating a sort override
owns only its presence bit; other source indicator bits remain intact. These
expectations are derived from the source and resolved intent, never from edited
headers or reconciliation's generated field values.

An explicit media-classification change also owns the primary video flag and its
secondary mirror when that field fits the retained MHIT header. Shared field
definitions establish presence; an absent mirror does not justify expanding an
older header. Unrelated edits preserve noncanonical retained pairs. New Tracks
populate both flags in the currently constructed header layout. Header selection
for new records across device/database generations remains a separate concern.

The existing review shows generated consequences. Inspection schema version 2
contains before, desired, resolved, and prepared values, generated record details,
causes, preservation constraints, and worker-stage durations. Durations describe
elapsed work, not successful completion, and do not affect result equality.

## Consequences

There is one editable representation and one derived execution account. Developers
can see automatic consequences before output exists without maintaining commands or
exposing private source bindings. Folder constraints and identity failures can be
reported with record context before reconciliation starts.

The public begin/analyze/prepare interface and physical save authorization remain
unchanged. No runtime dependency, editing feature, or general Sync capability is
introduced. Resource-dependent binary validation still occurs during preparation;
successful analysis alone is never permission to save.
