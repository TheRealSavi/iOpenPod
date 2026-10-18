# ADR-0148: Keep Album browse groups contiguous

- Status: Accepted
- Date: 2026-10-17
- Extends: ADR-0021 and ADR-0147

Issue [#255](https://github.com/TheRealSavi/iOpenPod/issues/255#issuecomment-6243799747)
reports repeated Albums on a Classic. Sort-4 indexes compared normalized Album
titles and then Track numbers. Distinct names such as `Nexus` and `The Nexus`, or
`f.e.a.r.` and `F.E.A.R.`, therefore interleaved. Native Album identities remained
distinct, and the verifier repeated the same faulty ordering. Explicit sort tags
did not prevent the collision.

Sort 4 orders complete semantic Albums before ordering their members. It keeps
the established Album identity: exact Album name, Album Artist with Artist as
fallback, compilation flag, show, and season. Each group's first member in
disc/Track-number order supplies the normalized Album and effective Album Artist
sort values; ties use that Master's occurrence order. Effective Album Artist
sorting prefers Sort Album Artist, Album Artist, Sort Artist, then Artist. Exact
semantic identity breaks remaining group ties. Within each Album, disc number,
Track number, and normalized title determine order, retaining Master occurrence
order on ties. This keeps one Album contiguous even with inconsistent member sort
tags, without changing Album equivalence or depending on optional native IDs.

Index positions address the particular Master's occurrences. Rebuilt alphabetical
jump ranges cover that order. Verification independently checks a complete
permutation, Album contiguity, ordering, and jump ranges. Other sort types,
including the separate sort-36 collation policy, retain their existing behavior.

An explicit `rebuild_album_indexes` Library Draft intent repairs existing sort-4
index/jump-table pairs without metadata edits. It requires unambiguous retained
pairs and, when membership is unchanged, complete Master occurrences. It preserves
unrelated native records and Unknown Data. Ordinary loading, serialization, and
default no-op drafts remain byte-exact. Repair alone does not invent absent index
pairs; structural edits retain their existing index-creation policy.

A user-directed Sync on a non-SQLite iPod with Tracks requests this repair. The
review screen offers **Refresh Library** with no selected changes, using the same
signing, source validation, cancellation, and recoverable Storage Transaction as
other Library writes. SQLite targets retain ADR-0147's regeneration workflow and
unchanged-CDB contract. This deliberately adds database preparation to no-change
Classic Syncs so users can repair previously generated indexes without retagging
or reimporting media.

Regression fixtures reproduce the reported collisions and exercise a virtual
Classic publication. Physical firmware confirmation remains separate evidence.
