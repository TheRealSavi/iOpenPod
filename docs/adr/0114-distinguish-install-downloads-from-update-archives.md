# ADR-0114: Distinguish install downloads from update archives

- Status: Accepted
- Date: 2026-10-04
- Amends: ADR-0109 and ADR-0110

## Decision

Use `Windows-x86_64.zip` instead of `Windows-AMD64.zip`. Keep macOS DMG names
unchanged and rename its update archives to
`iOpenPod-<version>-sparkle-update-macOS-<architecture>.zip`. Direct users to DMGs
for manual installation and reserve the ZIPs for Sparkle.

Released clients derive archive URLs from fixed names. The owner chose to publish
only the new names and require one manual upgrade, rather than keep duplicate
legacy downloads. Emit signed `updater_protocol: 2` for the new filename contract.
Protocol-1 clients, including 2.0.3, reject that metadata with their existing
manual-update error before attempting a download. New clients continue to verify
protocol-1 metadata using the original names, preserving signed release history.

Archive contents, installation layouts, helper protocols, trust keys, and the six
published native artifacts remain unchanged. The signed protocol selects a fixed
filename mapping; metadata still cannot supply arbitrary download destinations.
