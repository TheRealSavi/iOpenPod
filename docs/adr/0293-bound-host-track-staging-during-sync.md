# ADR-0293: Bound Host Track staging during Sync

- Status: Accepted
- Date: 2026-11-20
- Amends: ADR-0076, ADR-0087, ADR-0117 and ADR-0167

## Context

Issue #344 reports a Sync of more than 150 GiB with 50–100 GiB free on the
Host. All successful conversions outlived preparation until a single Library
save finished. Limiting concurrent encoders bounded working memory but still
required Host disk space proportional to the entire selection. Issue #342 also
reports growth while preparing existing Tracks for Rockbox file tagging.
Original iOpenPod v1.68.1 copied each Track from its transcode worker. The
current Storage boundary supports sequential device writes and verified
Library transactions, so a batch is the unit that can release Host files.

## Decision

Validate the complete selected Sync Plan before writing. Divide reviewed Track
work into batches with a target of one quarter of the free space on the Host
staging volume, up to 100 GiB. The ceiling takes effect at 400 GiB free.
Using the available space reduces repeated Library saves and verification on
large Syncs. Count the larger of the scanned source size and
the duration at the device's PCM or video bitrate ceiling. Include the sizes
of affected originals for replacement, tag updates and removal. An individual
Track that exceeds the target runs alone. Headroom allows concurrent captures,
encoder output, tag editing and transaction recovery. The target is an estimate.

Each batch prepares Tracks concurrently, verifies and commits its Library
through Storage, records Sync Details, then releases its Host files. For a
split selection, reviewed removals precede writes so incoming media can use
the space they release. Each transaction still validates actual capacity,
captures recovery material and checks device preconditions. Scrobbling runs
once. Host Playlist reconciliation uses the entire reviewed selection and
the identities actually committed by earlier batches. Podcast policy,
incoming Photos, Library-wide normalization and Genius run with the final batch.

Cancellation or failure can leave earlier verified batches on the iPod.
The result lists their completed actions. Recovery applies to the interrupted
transaction. A pending cleanup or failed Sync Helper publication stops further
batches. A fresh scan can use previously committed Sync Details when preparing
the remaining selection.

## Consequences

Large music selections can exceed available Host space. They incur a database
save and verification per batch. Encoding and device publication alternate at
batch boundaries. A single Track still requires enough space for its own
preparation. Database resources, Photo and Podcast preparation, Library-wide
tag changes and persistent recovery originals have their own space requirements.

During Library resource capture, file tagging reports the Track and processed
count. If the verified tag output matches the input bytes, release the private
copy immediately. For a retained Track, bind the original fingerprint as a
save precondition. For incoming media, keep its existing verified source.
