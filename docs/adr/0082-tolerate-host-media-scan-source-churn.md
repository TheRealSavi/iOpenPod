# ADR-0082: Tolerate Host Media Scan source churn

- Status: Accepted
- Date: 2026-09-25
- Extends: ADR-0063, ADR-0074 and ADR-0076

## Context

Host Media Library folders may be backed by iCloud Drive or another provider that
hydrates, evicts, replaces, or temporarily hides files while iOpenPod is scanning.
The previous final catalog check treated any such change as a failed scan. Folder
artwork was especially fragile because it is optional presentation data but was
required to remain byte-for-byte stable with the media catalog.

The Host Media Scan is used to prepare a Sync Review, not to authorize a device
write. A later Sync execution already validates current Host facts and captures
media through Storage before publication.

## Decision

The Host Media Scan publishes the best-effort snapshot it could inspect. Changes to
the selected catalog or folder availability become `HostMediaScanIssue` diagnostics
instead of aborting the scan. Files that cannot be inspected remain represented with
basic facts or are omitted according to the existing media-kind behavior.

Folder artwork is optional presentation data. A transient Storage failure while
finding or reading a folder cover yields no cover for that Track. Final artwork
observations reconcile the in-memory record so a stale cover is not retained merely
because it disappeared during the scan.

Playlist-review changes follow the same best-effort policy. An accepted external
file that changes before publication is omitted and reported. The scan does not
weaken Storage's path, identity, or read checks.

Sync execution remains responsible for revalidating current Host facts and for
capturing approved media before any iPod publication. A scan diagnostic therefore
does not grant stale source data write authority.

## Consequences

Selecting a cloud-backed folder no longer fails merely because the provider is
settling file state or a cover image is unavailable. The Review may contain a
partial or slightly stale snapshot and diagnostics, and the next scan can discover
files that appeared after the first enumeration. Changed files can still be skipped
during Sync preparation when Storage revalidation rejects them.

`HostMediaTreeChangedError` remains appropriate for lazy source reads after a scan;
it no longer represents ordinary catalog drift during the scan itself.
