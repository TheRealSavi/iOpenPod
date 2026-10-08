# ADR-0129: Validate Library files at workflow boundaries

- Status: Accepted
- Date: 2026-10-08
- Extends: ADR-0029, ADR-0030, ADR-0076, ADR-0117, and ADR-0120

## Context

Library preparation reread each source database five times. Retained-file tag
preparation read the complete media five times before Save, including a separate
fingerprint immediately before capture. Storage repeated preconditions and opened
a fresh recovery inspection after already verifying and committing the transaction.
Sync also validated unchanged media during both execution checks. On slow iPod
storage, these repeated reads dominated otherwise small edits.

## Decision

Assign validation to the boundary where its evidence is consumed:

- Preparation checks loaded databases early, then validates the complete captured
  resource set once when issuing the Storage Transaction. Association-only Sync,
  which has no transaction, checks the captured set explicitly. Resource capture
  and the coordinator do not each repeat that same complete scan.
- Storage returns the source fingerprint calculated while copying a Device file
  to the Host. It checks the open file and named path identity and connection,
  including replacement during capture. Artwork and retained-file tag preparation
  use this evidence without first reading the source solely to hash it. A Host
  transformation retains the original source fingerprint separately from its output.
- Save leaves database/file preconditions to Storage. Application checkpoints
  still validate the Active iPod, cancellation, signing identity, new Playback
  Sidecars, and explicitly discarded Track media.
- Storage validates before staging and after the final preparation callback,
  verifies staged content, and checks each destination before its atomic move.
  It does not repeat the complete precondition scan immediately before that callback
  or hash the same move source and destination twice before renaming them.
  The extra output-verification pass before removals runs only when removals exist;
  add/edit-only transactions retain final verification before commit.
- Successful transactions return their final verified file observations after
  persisting and flushing the committed journal. They do not reopen all files for
  another recovery inspection. Independent inspection and restoration still read
  complete content; restoration rejects later edits even if size and modification
  time are unchanged. Returned observations are evidence from commit, not a lease
  preventing future external edits.
- Host-backed recovery transactions check each remaining destination when its
  write publishes, rather than scanning every remaining destination for each write.
  Final dependency and result verification remains required.
- Sync validates media for selected changes and explicit associations at both
  execution checkpoints, with one observation per shared path per checkpoint.
  Unchanged items do not need these extra observations. The database source gate
  and final Library Sync Helper evidence checks remain independent.
- Sync reuses its validated immutable comparison for Playlist preview and draft
  reconciliation, instead of rebuilding the same full comparison three times.

## Consequences

Preparation now fingerprints each source database twice. Capturing and validating
a retained-file tag edit or changed artwork prefix requires two complete Device
reads: one copy and one final check. Ordinary database-only renames read no media.
Library and Sync share the same improved publication path for additions, edits,
and recoverable removals. Ordinary permanent Track deletion retains ADR-0128.

Rockbox tag edits still rewrite the complete media file. Required staging, output
verification, recovery copies, capacity checks, journals, and connection validation
remain. No timing guarantee is made for physical devices. Regression tests count
expensive reads and comparisons independently of Host caches and USB throughput.
