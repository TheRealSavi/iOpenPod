# ADR-0220: Version SysInfo Authority cache invalidation

- Status: Accepted
- Date: 2026-10-31

Legacy transport revisions can survive as firmware in a consistent SysInfo cache,
including one carrying a RetailOS provenance marker. Preserve ADR-0175's cache
reuse while invalidating these records once for every iPod model.

Centralize the existing SysInfo Authority `version` in
`device_registry.authority.SYSINFO_AUTHORITY_VERSION` and bump it from 1 to 2.
Cache reuse requires this exact integer version as well as matching file hashes
and hardware provenance. A future invalidation increments the same constant.
Older, missing, malformed, or unknown versions cannot supply trusted provenance
during reconciliation either; rewriting metadata alone cannot certify an old
firmware value. Models with cached firmware require its validated provenance even
when their capabilities do not depend on firmware. A failed firmware recapture
therefore remains eligible for retry on the next full inspection.

Discovery stays read-only. Selecting the iPod reconciles the actual vendor
`VisibleBuildID` into SysInfo, SysInfoExtended, and SysInfo Authority using existing
atomic replacement and verification. SCSI/FireWire revisions remain transport
evidence and are never substituted for a missing firmware release. Probe failures
retain existing access diagnostics and metadata fallback; a fresh release cannot
be invented when the device or Host does not supply one. Read-only Volumes still
report skipped repair rather than being mutated.

After successful capture and selection-time repair, the current-version cache is
reused across explicit refreshes, reconnects, and app restarts. Unchanged automatic
polling continues reusing the current Connection Generation's evidence. This is
cache invalidation, not continuous detection of firmware replacement when cached
files remain unchanged.

Virtual-device regressions cover Video 5/5.5, Classic, nano, and Mini legacy caches,
including incorrect caches carrying a valid RetailOS marker. Tests verify one-time
repair, reconnect reuse, future version bumps, failed capture retries, separate
transport values, Games qualification, and unchanged discovery bytes. Physical
acceptance of the reported device remains unverified.
