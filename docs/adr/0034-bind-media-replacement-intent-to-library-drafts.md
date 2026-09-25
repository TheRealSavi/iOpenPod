# ADR-0034: Bind media replacement intent to Library Drafts

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0021 and ADR-0025

Different file content can have the same projected Track metadata. Deriving media
requirements only from snapshot differences cannot represent that replacement.
Treating supplied Prepared Media as intent would also allow resource inputs to
silently expand a draft's requested changes.

`IPodLibrary.begin_draft(..., replace_media=(track_id, ...))` therefore records
explicit replacement intent on the immutable, source-bound Library Draft. Every
identity must occur once, belong to the source snapshot, and remain in the desired
snapshot. Additions and changes to media-owned fields continue to require Prepared
Media without this option. Combining either kind of field edit with explicit
replacement requires only one Prepared Media record per Track.

Analysis reports each explicit replacement as a `LibraryChange` with subject
`media`, action `replace`, and the affected Track ID. This describes content intent
without inventing a changed Track field. Its `media.replacement` Write Effect links
back to that change; unrelated browse, Playlist, and artwork dependencies remain
unchanged. Preparation derives requirements again from the draft, so public plan
summaries cannot add authority or remove requirements.

Replacement follows resource validation, reconciliation, serialization, signing
when required, and independent verification even when the snapshots are equal.
Reconciliation consumes the supplied native codec facts; verification compares the
reparsed fields against those facts independently. Semantic metadata retains its
existing ownership rules. Native diagnostics in the submitted Track remain copied
from the source; the resulting snapshot reports the prepared native values.
Unrelated fields, Unknown Data, Track identities, and retained header lengths stay
protected. Existing signature and format restrictions still apply.

Prepared output includes the replacement's captured `FileDependency`, even when
the database bytes also remain identical. iPodDB neither observes the old media
content nor publishes files. The Application Layer must capture old-file
preconditions and compose a reviewed Storage Transaction before a replacement can
be saved. Application replacement UI/publication, conversion, and Sync remain
separate work; this decision introduces no new dependency.
