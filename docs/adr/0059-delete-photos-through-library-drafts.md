# ADR-0059: Delete Photos through Library Drafts

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0053, ADR-0054, and ADR-0058

## Context

The Photos browser exposes a disabled **Delete Photos** placeholder even though the
common Library workflow already provides explicit omission intent, verified
PhotosDB preparation, review, and recoverable Storage Transactions. Original
iOpenPod removes the selected semantic Photo from the PhotosDB image collection and
every Photo Album, and removes its retained full-resolution file when one exists.

Deleting a Photo is not the inverse of importing one. It requires no image-ID or
iTHMB allocation, but it must still prevent dangling Album membership, unsafe path
deletion, and a database that references a file after that file has disappeared.
Packed iTHMB files can contain ranges for many Photos and cannot be safely compacted
as though they were one file per Photo.

## Decision

- `LibraryWorkspace.remove_photos` accepts one revision-checked semantic selection,
  omits those Photos, removes every occurrence from every Photo Album including the
  Master Photo Album, and records explicit omission intent. The edit remains
  reversible until the existing review and save workflow succeeds.
- iPodDB independently requires omission intent for each removed Photo, preserves
  the relative order of surviving Photos, rejects dangling Album references, and
  permits only the exact Master Photo Album membership pruning caused by the Photo
  deletion. Other Master Photo Album edits remain blocked.
- PhotosDB reconciliation removes each omitted MHII and its requested MHIA
  occurrences through the retained, definition-driven document writer. It preserves
  file-format records, root allocation values, unrelated children, Unknown Data, and
  packed thumbnail bytes.
- The Application Layer captures each removed Photo's unique, unshared
  full-resolution file only beneath `Photos/Full Resolution`. Its current
  fingerprint becomes a Storage precondition and, when the file exists, one
  recoverable Transaction removal. PhotosDB is published before those removals.
- Photo iTHMB files are not compacted, rewritten, or removed. Their now-unreferenced
  ranges remain inert retained bytes. Photo import and reclamation of packed
  thumbnail space require a separate allocation policy.
- The Photos context menu confirms the selected count and stages the deletion in the
  Library Draft. It does not write directly to the iPod.

## Consequences

Users can delete one or many Photos through the same review, verification, stale
source checks, and recovery contract used by other Library changes. A surviving
Photo that shares a full-resolution path prevents that file from being removed.
Missing originals do not block metadata cleanup, while an unexpected path outside
the full-resolution subtree blocks the review before publication.

Deleting Photos does not immediately reclaim packed iTHMB space. Adding Photos,
changing representations or file formats, and editing or deleting the Master Photo
Album directly remain unsupported.
