# ADR-0145: Select Track layouts for all Library writes

- Status: Accepted
- Date: 2026-10-15
- Extends: [ADR-0144](0144-expand-track-headers-with-device-capabilities.md)
- Amended by: [ADR-0171](0171-use-standard-track-headers-on-mini-2-and-ipod-video.md),
  selecting 624-byte headers for Mini 2G and full-size iPod 5G/5.5G.

## Context

New Tracks always received a 624-byte MHIT, regardless of the selected Device
Profile. Composer, album/artist, and artwork reconciliation could also assign
fields after the existing header expansion decision. A short Track could therefore
accept artwork only when an unrelated edit happened to expand its header first.

The [source and capture review](../research/adjacent-playback-compatibility-review.md)
compares Original iOpenPod, libgpod, foo_dop, and six retained databases. They show
different writer choices, including 584-byte records and larger headers on older
device labels. Neither the 1.x size table nor a retained root version establishes a
universal firmware maximum. The current physical Device Profiles select `0x13`,
`0x19`, or `0x30`; they do not use the disputed earliest historical versions.

## Decision

The existing shared MHIT size policy now also selects the extent of newly created
Library Tracks when `WriteTarget.database_version` is supplied. Current physical
profiles therefore author 328-byte or 624-byte headers. Generic callers without a
Device Profile retain the 624-byte creation default; absence of a profile still
does not authorize expansion of an existing record. This supersedes ADR-0144's
decision to leave new Track creation unchanged.

The device baseline, rather than the retained root version, selects the new extent.
Existing Tracks retain their original size unless an intended field requires
authorized expansion. Larger and nonstandard retained headers are never shrunk.
Creation or expansion raises the root version to at least the supplied baseline,
without downgrading a newer source. These are explicit authoring choices, not
claims that other sizes are rejected by firmware.

Before editing Tracks, Library reconciliation derives requirements for later
composer, album/artist, and artwork updates from the source and resolved intent.
Affected browse-group members participate even when their own metadata is
unchanged. Those requirements join direct metadata and media fields in the existing
expansion decision. Verification derives the expected extent from the same source
and intent, independently of candidate fields and allocated identities.

Optional native representations have named policies. New secondary persistent IDs
and duplicate sizes are written only when the chosen layout contains them. Composer
text remains in MHOD 12 when the layout cannot hold `composer_id`; existing larger
headers continue to use their native IDs. Artwork retains reverse linking where a
direct reference is absent; an optional direct reference alone never forces growth.
Changes to an existing album or artist dataset must still encode its required
Track references, or fail preparation. No blanket out-of-bounds field suppression
is introduced. Semantic history and all other requested fields must fit or the
write is blocked with source evidence intact.

## Consequences

Nano 5G/6G/7G continue to use the 624-byte policy and their existing signing,
compression, SQLite, and sidecar recovery paths. Earlier nano 1G/2G and full-size
5G/5.5G use 328 bytes for new Tracks. The evidence does not justify new model-name
exceptions or changes to MHBD, MHYP, or MHIP sizing.

Public Library tests cover creation, independent artwork/composer edits, indirect
browse-group changes, optional IDs, rejection of unstorable history, larger retained
records, no-op bytes, and verifier rejection of incorrect extents. Existing nano
integration tests cover skip history and publication artifacts. Physical firmware
acceptance remains untested; retained captures are not a substitute for that test.
