# ADR-0029: Publish file transactions with retained recovery

> ADR-0093 makes terminal cleanup automatic after successful Library saves and
> during selected-device loading; the Storage recovery checks remain required.

- Status: Accepted
- Date: 2026-09-11
- Extends: ADR-0011 and ADR-0022

The requested media and artwork write workflows change several dependent files.
Sequencing independent replacements cannot retain one writer lease or recover an
interruption as one operation. Storage will accept an immutable ordered transaction
of writes, recoverable removals, and unchanged file dependencies. It will stage and
verify all new content, retain replaced originals, and persist an Operation Journal
before publishing targets. Host files stream through bounded buffers. The application
owns ordering and format meaning; Storage owns filesystem access and recovery.

Publication is individually atomic and ordered, not an instantaneous filesystem-wide
swap. Removals follow verification of all writes and move originals into retained
recovery storage. Journals distinguish staging, prepared, publishing, committed,
restoring, and restored states. No backup preference controls this protection.
Capacity validation reserves space for staging, retained originals, and restoration.
Cancellation is accepted before publication. A disconnect stops the session and
leaves evidence for a new connection; it cannot promise immediate rollback.

Recovery inspects the journal and all affected files, then restores only over that
exact observation. It validates every target, unchanged dependency, and required
original before modifying any target. An unrelated later edit blocks recovery.
Physical Device and Volume identities must match, while a new Connection Generation
is required after reconnecting. Restoration reverses publication order, preserves
recovery content, and can resume after another interruption. Recovery data and empty
staging directories are retained until a separate explicit cleanup workflow manages
them. Existing single-file replacement journals remain supported.

This records the transaction contract, not completion of Sync. Application resource
capture, review, and transaction composition must be connected and verified before
media/artwork saving is exposed. Database format blockers remain independent.
