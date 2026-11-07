# ADR-0171: Use standard Track headers on Mini 2 and iPod video

- Status: Accepted
- Date: 2026-10-23
- Amends: [ADR-0144](0144-expand-track-headers-with-device-capabilities.md) and
  [ADR-0145](0145-select-track-layouts-for-all-library-writes.md) for Mini 2G and
  full-size iPod 5G/5.5G Device Profiles.

## Context

Podcast Sync can fail on these profiles when the retained iTunesDB contains an
artist dataset. Their 328-byte authoring layout cannot encode the required
`artist_id_ref` at offset `0x1E0`. The lossless writer correctly rejects that
unrepresentable relationship. The same conflict can affect other media additions
and artist-group edits.

The maintainer reports evidence that the standard 624-byte MHIT works on Mini 2G
and full-size iPod 5G/5.5G, and explicitly approves using it on these models.
This compatibility evidence is supplied by the maintainer; this change's software
tests do not constitute a new physical-device validation run.

Original iOpenPod selected its MHIT size from the greater of the device baseline
and retained root version. ADR-0145 deliberately selects from Device Capabilities
instead. This change updates those capabilities while keeping the existing shared
size policy and lossless reconciliation contract.

## Decision

Mini 2G and full-size iPod 5G/5.5G select binary database baseline `0x30`, which
already maps to the standard 624-byte Track header. Mini 2G receives a distinct
capability variant; Mini 1G and the other older profiles retain their baselines.
Signing, compression, SQLite, artwork, media formats, and database size limits
retain their existing independent capabilities.

New Tracks use 624 bytes. Existing Tracks expand only when requested native fields
or affected browse relationships require it, preserving Unknown Data through the
existing expansion path. No-op preparation stays byte-exact; larger retained
headers never shrink. Creation or expansion raises the root version to at least
`0x30` without downgrading a newer source. Device metadata reconciliation reports
the same updated baseline in SysInfoExtended's `DBVersion`.

No fields or datasets are discarded, and the binary serializer still rejects
unrepresentable values. No model-name branches are added to iPodDB.

## Consequences

Podcast imports can encode their artist references on these models, including
affected existing Tracks that previously had short headers. Registry coverage
checks every catalog variant of the three generations and unchanged neighboring
profiles. Application-level Library preparation tests exercise Podcast creation,
retained short-header expansion, artist relationships, older and newer root
versions, and unchanged source bytes using the real Device Profiles.
