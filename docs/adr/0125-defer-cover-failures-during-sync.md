# ADR-0125: Defer cover failures during Sync

- Status: Accepted
- Date: 2026-10-07
- Extends: ADR-0076 and ADR-0084

## Context

The owner requested that thumbnail problems stop blocking otherwise usable Sync
changes. Accepting valid mixed F1061 layouts addresses one compatibility case,
but missing, truncated or unreadable artwork files can still prevent preparation.
Optional covers should not prevent verified media from reaching the iPod.

## Decision

When Library preparation fails and the Sync draft requests cover changes, the
Application Layer retries preparation once with existing Track cover associations
retained and new Tracks assigned no cover. The retry clears new Artwork Assets
but preserves the rest of the reviewed draft, incoming media, Photo changes,
Podcast history and explicit embedded-artwork updates. It uses the complete
ordinary preparation, verification and Storage Transaction path.

Only a successful verified retry defers the original errors. Sync reports a
nonblocking cover warning and a partial result, saves the remaining changes, and
records an empty Host artwork fingerprint so subsequent scans can retry cover
updates or removals. If the retry also fails, both attempts' diagnostics remain
available and no candidate is published. Cancellation remains effective between
attempts. Storage publication failures retain their existing recovery behavior.

This is Sync policy, not permissive iPodDB encoding. Direct Library reviews still
report unfulfillable edits rather than silently changing their requested result.
The fallback does not authorize overwriting malformed thumbnail files or replacing
retained covers with placeholders.

## Consequences

Artwork encoding or capture problems no longer prevent independent Track Sync
when the draft without cover changes verifies successfully. New Tracks can arrive
without artwork, and existing Tracks can retain older artwork. Deferred covers
remain visible as pending work on a subsequent scan. A failed first attempt can
require a second capture of media resources. Disconnects, changed source databases,
insufficient transaction space and independently invalid Library edits still
prevent unsafe publication.

Virtual-device regressions verify media additions and updates with missing,
truncated and non-file thumbnail paths, unchanged ArtworkDB bytes, preserved
existing cover links and retryable Sync Details.
