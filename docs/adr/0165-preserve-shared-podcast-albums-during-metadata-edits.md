# ADR-0165: Preserve shared Podcast albums during metadata edits

- Status: Accepted
- Date: 2026-10-21
- Amends: ADR-0145, ADR-0152, and ADR-0153

## Evidence

Normalize Tags on a connected Nano 5 stopped during preparation, before device
publication. A private replay reproduced the failure with two sort-field edits
on Episodes sharing one native album. Optional Show and Album Artist tags divided
those Episodes into separate semantic browse groups. Reconciliation rewrote the
same native album once per group; verification then rejected its representative
Track and Show metadata against the other group. Serialization was not the cause.

The per-show relationships established by Podcast Sync were valid. Applying the
music-style sort-4 grouping contract to native Podcast album ownership conflicted
with ADR-0152 and ADR-0153.

## Decision

- Ordinary metadata saves retain each source Podcast album across differences in
  Episode artist, Album Artist, Show, compilation, and season. Native album grouping
  is distinct from the unchanged sort-4 browse grouping policy.
- Album title and feed identity still distinguish shows. Missing feeds join only
  one unambiguous feed within a retained album. Explicit title or feed edits can
  split members into a new album. Separate source albums remain separate; merging
  duplicates belongs to explicit Podcast normalization.
- A new Episode may join one unambiguous retained album with a compatible title
  and feed. Multiple candidate albums are not selected arbitrarily.
- Unchanged Episode values preserve the retained album's show-level text,
  compilation, and season, including absent optional records and private bytes.
  Changed values use the existing first-member/first-nonempty selection policy
  across all members of the native album. A rewritten Podcast album has content
  type 3 and a representative belonging to its remaining Episodes.
- A changed native record shared by incompatible groups, including conflicting
  feeds or music ownership, blocks preparation. Unrelated edits and no-op writes
  do not repair existing anomalies implicitly.
- Header requirements, reconciliation, and verification use the same source and
  desired grouping inputs. Verification still independently checks serialized
  identities, representatives, edited metadata, and preserved show-level values.

## Validation

Public preparation tests cover shared albums, individual and simultaneous sort
edits, explicit show changes, deletion, separate source albums, incompatible
ownership, lossless no-ops, and injected output corruption. Existing Episode
addition, Podcast Sync, music browse, and header-expansion tests remain applicable.

The complete Normalize Tags suggestion is replayed against private Host copies of
the Nano's CDB and retained SQLite databases, with its signing material and SQLite
postprocessing. Checks cover all 98 suggested fields on 75 Tracks, preserved native
album identities and Podcast metadata, verified signed outputs, and an empty second
normalization. This verifies preparation; physical firmware acceptance still
requires using the resulting Library on the device.
