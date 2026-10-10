# ADR-0021: Prepare Library Drafts over retained Database Documents

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0019 and ADR-0020
- Application rule-application and saving behavior extended by [ADR-0022](0022-apply-and-save-playlist-drafts.md).
- Unrecognized sort-36 collation uses a warning and default order under [ADR-0137](0137-warn-and-default-unrecognized-album-collation.md).

## Context

The Library Snapshot makes application editing straightforward but cannot represent
all binary metadata, duplicate occurrences, firmware lists, or artwork ownership.
Serializing it as a replacement database would discard information. Exposing Chunks
to the GUI would also reverse the boundary established in ADR-0019. The existing
definition-driven writers already provide the lossless output path.

The user approved a complete desired-state submission interface, verified output,
and a review UI, while leaving physical Sync, new editing screens, compressed
databases, and SQLite companions separate.

## Decision

`IPodLibrary` retains the authoritative original Database Documents and original
projection. `begin_draft` binds a complete desired snapshot to an opaque source
revision. `analyze` returns immutable changes, requirements, and diagnostics;
`prepare` checks those inputs again, reconciles retained documents, serializes,
finalizes supported signatures, reparses, and verifies the candidate. None performs
filesystem access. `serialize()` continues to reproduce the unchanged source.

Missing previously projected Tracks or Playlists request deletion. A draft defaults
to `delete_omissions=False`: each omission is a blocking diagnostic. The caller must
explicitly set `delete_omissions=True` when creating a draft with intentional
deletions. This permission belongs to that immutable draft and is revalidated by
preparation; it does not bypass any other checks. Rejecting omissions, rather than
silently restoring records, retains the complete desired-state contract and makes
accidental submission of a filtered snapshot visible. Removing a Playlist entry
does not delete its Track and does not need this opt-in. Hidden records
are never deleted merely because the projection omits them. Values are compared
with the original projection before encoding. Display-only hierarchy repairs,
noncanonical flags, duplicate metadata, and unknown bytes remain unchanged unless
their semantic dependency actually changes. Ambiguous affected structures block
preparation; unrelated source inconsistencies are retained and reported.

`Playlist.entries` holds `PlaylistEntry` records. Their opaque identities are scoped
to one Playlist in one source revision. Duplicate Tracks have distinct occurrences.
`track_ids` is derived. Reorder entries themselves to move duplicate occurrences
without exchanging their private metadata. Source locations and occurrence bindings
remain private to the adapter; common records contain no Chunks.

Editable semantic values, media-derived values, artwork-derived values, and native
diagnostics have different ownership. Additions and media replacements require
explicit prepared codec facts and captured file identities. Artwork changes require
bounded RGB888 pixels or a verifiable existing image reference. Read-only native
diagnostics cannot be submitted as edits. Existing identities are retained; additions
receive available native identities, returned with the resulting snapshot.

ArtworkDB and iTHMB preparation form one candidate with iTunesDB. Replacements append
to verified source-file prefixes, using the supported `F<format>_<shard>.ithmb`
namespace and a captured inventory. Old ranges and photo data remain. Shared images
are cloned for replacement. Clearing an association removes direct Track references
and every reverse ownership link for that Track. The first ArtworkDB requires an
explicit, evidenced root value because its field at 0x10 is not universally known.

Signature requirements belong to artifacts. `WriteTarget.checksum` describes
iTunesDB; `artwork_checksum` separately describes ArtworkDB. The implemented output
scope is unsigned or HASH58 iTunesDB and unsigned ArtworkDB. Unsupported required
signatures, compressed output, and SQLite companions block changed candidates.
An unchanged draft still reproduces its source bytes. This distinction matters
because a device may require HASH72 for a SQLite companion rather than iTunesDB;
see the [libgpod format overview](https://github.com/fadingred/libgpod/blob/master/README.overview).

Stable diagnostics retain severity, phase, record, field, actionable text, and
optional binary context. Independent validation errors are collected. Any error
withholds the entire Prepared Library. Warnings accompany successful output;
unavoidable numeric quantization reports the stored result. Unexpected implementation
exceptions remain failures with technical logging, rather than validation messages.

The Application Layer captures the Active iPod, source fingerprints, workspace edit
revision, and Connection Generation. It runs preparation in the background and
discards obsolete or cancelled results. Review Changes displays changes and grouped
diagnostics, with record navigation and optional technical detail. Success is
**Prepared for review**. Preparing never marks a draft saved or replaces the loaded
Library, and physical Sync remains disabled.

Smart Playlist previews are independent of saved membership. This supersedes
ADR-0020's earlier session-editor behavior that copied explicit rule previews into
the draft's saved entries. Editing rules now retains saved entries; a newly created
Smart Playlist has no saved entries until an explicit, supported membership workflow
establishes them. Preparation never runs the preview evaluator.

## Consequences

The UI submits ordinary immutable records through one application request. The
semantic layer is an editor of retained documents, not another binary serializer.
There is no runtime dependency on Original iOpenPod and no new runtime dependency.
Original HASH58 output supplies fixed vectors; its positional, folder, group, and
artwork knowledge supplies regression evidence without importing destructive rebuild
behavior.

Prepared output is a review artifact, not a device commit or a claim of hardware
compatibility. Retained artwork ranges and captured source dependencies travel with
the result. Pending positional playback sidecars block structural Track edits until
their context can be reconciled. Unproven artwork layouts, ambiguous dataset mirrors,
and unsupported affected rules require explicit future support rather than repair
by inference. Details and current limits are in [Library writing](../library-writing.md).
