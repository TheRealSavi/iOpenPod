# ADR-0258: Carry rating decisions through Sync

- Status: Accepted
- Date: 2026-11-13
- Amends: [ADR-0252](0252-persist-retryable-rating-back-sync-state.md)

## Decision

Resolve each established pair in the reviewed Sync Plan using the selected
conflict policy. The Library Draft, pending Host writes, and post-save Back Sync
use that decision. Review shows each target. Changing the setting or policy
requires a fresh Review.

Keep the versioned rating catalog and the v7 Library Sync Helper. Record
pending intent before the iPod save. Acknowledge a completed Host write in the
rating catalog after publishing its Sync Details in the Library Sync Helper.
If that publication fails, the pending intent remains available on the next
scan, which can recognize a Host rating already at its target.

Keep the Host Media Scan Cache at v17. Storage ensures atomic Host replacement
changes either the file size or the modification time. When both match the
reviewed source, Storage advances the timestamp on the staged file and verifies
that the filesystem stored a distinct value before replacement. If the
filesystem cannot represent a different timestamp, the Host write fails and
remains retryable. Sync Details records the actual published file facts.

## Consequences

The Host cache needs no new identity fields or one-time metadata refresh beyond
the native rating refresh already required by v17. An external replacement that
preserves size and modification time can still evade the ordinary cache check.
