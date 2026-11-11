# ADR-0252: Persist retryable rating Back Sync state

- Status: Accepted
- Date: 2026-11-11
- Extends: ADR-0065, ADR-0120, and ADR-0123

## Context

Rating Back Sync can commit an iPod rating and then fail while replacing a
Host file. The committed iPod value can change the conflict resolution on retry.
Adding rating fields to v7 of the Library Sync Helper also makes the portable
helper unreadable by installations that already use v7.

## Decision

Keep the v7 Library Sync Helper schema readable by existing installations.
Record rating baselines and pending Host writes in the separate versioned,
checksummed `iPod_Control/iOpenPod/rating-sync.json` catalog. Associate each
record with a persistent Track identity and the Host path from Sync Details.
Move inline ratings from preview builds into the separate catalog on successful
helper publication.

A reviewed Sync can establish missing rating baselines for a known pair
without changing either rating. Unread Host metadata cannot establish a baseline
or count as a cleared rating.

When the chosen result requires a Host write, record the reviewed Host rating
and target through Storage before publishing iPod changes. Host replacement
still follows verification of the committed iPod Library. On retry, reuse the
target if the current iPod rating equals it and the Host rating equals the
reviewed value or the target. Revalidate the reviewed Host file before replacing
it. Successful publication records the observed baselines and clears the pending
write. Corrupt rating state is preserved and disables rating reconciliation.

Host Media Scan Cache v18 checks file identity in addition to the existing
Track file facts. Atomic replacement can change identity while preserving size
and modification time. Reuse of older Acoustic Fingerprints continues during
the one-time metadata refresh.

## Consequences

Read-only review leaves both device catalogs untouched. A Host write or
helper publication failure can be retried after a new scan and Review. A
same-size in-place edit that preserves modification time and file identity
still falls outside the scan cache freshness check.
