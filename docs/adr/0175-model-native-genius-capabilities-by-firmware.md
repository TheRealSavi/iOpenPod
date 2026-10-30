# ADR-0175: Model native Genius capabilities by firmware

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0010 and ADR-0013

## Context

The physical Genius experiments established Track-seeded Playlist creation on a
120 GB Classic running RetailOS 2.0.1 and native Mix playback on a nano 7G running
1.0.4. Apple's release notes introduce Classic Mixes with 2.0.3 for the later
160 GB model. A shared Classic capability bundle or SQLite support alone cannot
describe these differences. Firmware support also does not establish that
iOpenPod can generate and preserve the required data through Sync.

Current version evidence conflates SCSI/FireWire revisions with RetailOS releases.
The connected Classic reported FireWire revision 1.62 and `VisibleBuildID=2.0.1`;
the nano reported revision 1.70 and `VisibleBuildID=1.0.4`. Internal `BuildID`
values are a third namespace. Comparing transport or internal build versions to a
RetailOS requirement would produce incorrect capability decisions.

## Decision

- Add an immutable `GeniusCapabilities` group to Device Capabilities with separate
  native Playlist and Mix support. `FeatureSupport` has supported, unsupported,
  and unknown values; consumers must explicitly require supported.
- Catalog entries describe stock firmware for marketed models. Classic 6.5G and
  nano 4G support native Playlists. Classic 7G and nano 5G–7G also support native
  Mixes, with Classic 7G Mixes conditional on RetailOS 2.0.3 or later. Earlier
  release-target models have neither feature. Cross-flashed firmware is not
  inferred from a version string on an older model.
- The Classic 7G catalog baseline carries an unknown Mix state and the numeric
  requirement `(2, 0, 3)`. Exact identification refines a copy using the highest
  authority release observations. Missing, malformed, or conflicting observations
  at that authority leave Mix support unknown; they do not block exact hardware
  identification and do not fall back to lower-authority versions. Catalog lookups
  and ambiguous candidates retain the baseline.
- `DeviceEvidence.firmware_versions` contains user-visible RetailOS releases from
  `VisibleBuildID`/`visibleBuildID`. A separate `transport_revisions` collection
  retains FireWire and SCSI revisions. Internal build numbers do not become
  release evidence. Metadata reconciliation writes the two version namespaces
  to their corresponding keys and preserves unrelated metadata.
- Cache the observed release in both SysInfo files and retain its recorded hardware
  provenance in the existing version-1 SysInfo Authority fields. A firmware-dependent
  profile can skip probing only when that release agrees across both hash-verified
  files and has hardware provenance marked `value_kind: retailos_release`. Only
  current release evidence can establish this marker; metadata-only reconciliation
  can preserve it but cannot certify an unmarked legacy value. Older incomplete or
  inconsistent caches trigger a read-only probe and selection-time repair. A complete cache remains
  reusable across connections as Device Metadata; this does not detect firmware
  replacement when the cached files are unchanged. Profiles without a firmware
  requirement continue caching available release evidence without requiring it.
  Game-capable profiles also require validated RetailOS provenance, because Games
  authorization is qualified by exact release. This includes Classic 6.5G even
  though its Genius Mix capability is not conditional. An unmarked legacy SCSI
  revision cannot suppress the read-only probe needed to repair these caches.
- Storage remains generic. The Application Layer places generic probe revisions
  in transport evidence; Device Registry parses already-read vendor payloads,
  resolves capabilities, and returns metadata bytes without I/O.
- This change adds no Genius generator, Playlist importer, Mix encoding, GUI
  action, or Sync preservation policy. Those require subsequent decisions and
  implementation. Native support does not imply data readiness or hardware
  validation of iOpenPod's authoring on every model.

## Verification

Tests cover every catalog variant, the Classic 2.0.2/2.0.3 boundary, numeric version
ordering, missing/conflicting evidence, evidence authority, catalog immutability,
older-model exclusions, version parsing and reconciliation, and read-only virtual
discovery. Virtual-device tests also cover legacy-cache repair, recorded release
provenance, unchanged discovery bytes, and cache reuse after reconnecting. No
physical device writes are needed to test the registry policy.

The [capability matrix](../genius-capabilities.md) records sources and the narrower
physical validation status. Original iOpenPod remains a research baseline, not a
runtime dependency.
