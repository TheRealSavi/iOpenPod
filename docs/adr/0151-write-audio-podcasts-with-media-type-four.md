# ADR-0151: Write audio Podcasts with media type four

- Status: Accepted
- Date: 2026-10-19
- Supersedes: ADR-0149's audio Podcast media-mask choice

## Context

ADR-0149 selected Audio plus Podcast, native media type 5, from the earlier Finder
captures. A subsequent comparison found type 4 in both an iTunes 12.6 baseline and
a newer device-management capture, while iOpenPod publication added the Audio bit.
The requested authoring policy is now native Podcast type 4. Captured type 5
remains valid input evidence and must still be readable without changing its bytes.

## Decision

The Application Layer classifies incoming audio Podcast Episodes and desired audio
Podcast Tracks as `MediaType.PODCAST` alone, which the existing iPodDB writer
encodes as 4. Shared playback policy applies this to conversion, metadata edits,
Library saves, and Sync, including retained audio Podcasts previously stored as 5.
The policy continues to require resume playback, skip shuffle, and Podcast Now
Playing flags and to preserve supplied or retained disc numbers.

Video Podcasts retain their video classification, including native type 6. iPodDB
continues to read compound classifications and preserve unchanged documents
exactly; merely loading a Library does not convert type 5 to 4. The correction is
an explicit Application Layer Draft published through the existing Storage path.

## Consequences

New audio Episodes use type 4, and existing type-5 audio Podcasts become type 4 on
the next application save or Sync. Media content and persistent Track identities
are retained. No dependency, parser definition, or database schema changes.

Regression coverage checks import classification, conversion, metadata actions,
published Podcast Sync bytes, and prepared iTunesDB/iTunesCDB output from retained
types 4, 5, and 6, alongside unchanged-document round trips.
