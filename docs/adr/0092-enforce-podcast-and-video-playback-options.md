# ADR-0092: Enforce Podcast and video playback options

- Status: Accepted
- Date: 2026-09-27
- Amends: ADR-0088's preservation of all other metadata during reclassification

## Context

Podcasts and videos must remember their playback position and stay out of shuffle.
Setting these options only in Convert to Podcast leaves other imports,
reclassification, and ordinary metadata edits able to produce inconsistent Tracks.
Previously saved Tracks can also have either option disabled.

## Decision

A shared Application Layer policy requires `remember_position` and `skip_shuffle`
for Podcast and video classifications, including Video Podcasts, Movies, TV Shows,
Music Videos, and compound audio/video classifications. A retained Podcast marker
also identifies a Track that requires the policy. Music and Audiobook options
remain editable.

Podcast and Video Podcast classifications also require the Podcast Now Playing
marker (`TrackMetadata.podcast`). The existing iPodDB field mapping writes native
MHIT `podcast_now_playing_flag` at `0xA7` as `0x01` when enabling this marker,
matching Original iOpenPod's audio and video Podcast conversion. An existing
enabled native value, including the recognized alternate `0x02`, is preserved by
selective writing. This is not a new bitmask or a reason to normalize retained raw
bytes. Non-Podcast video classifications do not acquire the Podcast marker.

Incoming Tracks, reclassification, and metadata edits apply this policy. Library
Draft preparation and Sync also repair retained Tracks whose required flags are
off, without replacing their media. The editor and context menu prevent disabling
required flags while still showing the actual saved state until it is repaired.

The policy belongs to iOpenPod rather than iPodDB. Loading or round-tripping an
unchanged database preserves its bytes and metadata; a correction is an explicit
Application Layer Draft published through the existing verified transaction.
Reclassification continues to preserve media, identity, and unrelated metadata.

## Consequences

- All application publication paths share the same playback rule.
- Existing incorrect options are repaired with the next Library save or Sync.
- Regression coverage checks both application edits and saved database values.
- No dependency, database schema, or low-level parsing behavior changes.
