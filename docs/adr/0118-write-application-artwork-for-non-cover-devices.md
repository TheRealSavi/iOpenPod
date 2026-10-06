# ADR-0118: Write application artwork for non-cover devices

- Status: Accepted
- Date: 2026-10-05
- Extends: ADR-0012, ADR-0030, ADR-0032, ADR-0033, and ADR-0076

## Context

Some supported iPods, including the second-generation iPod mini, have no native
firmware album-art capability. iOpenPod can nevertheless browse their Libraries
with its own lazy ArtworkDB/iTHMB reader. The previous implementation exposed a
display-only `F1060` read fallback but skipped Host and embedded artwork during
Sync and Music import, so newly synced Tracks had no artwork identity or readable
representation in iOpenPod.

## Decision

The Application Layer uses the Device Profile's native cover layouts when they
exist. When a profile has none, it captures and writes one iOpenPod-only cover
layout: `F1060`, 320x320 RGB565 little-endian, with ArtworkDB root policy `2`.
This layout is application storage, not a claim that the iPod firmware can
display album artwork; Device Registry `supports_cover_art` remains false.

The same application layout policy is used by Host Sync, Podcast Sync, embedded
artwork import, Library preparation, and lazy device artwork reads. All output
continues through the existing reviewed Library write and recoverable Storage
transaction. Existing ArtworkDB roots and retained records remain authoritative.

When Rockbox Metadata Support is enabled, Sync also embeds the captured artwork in
each prepared media file. Native cover-capable profiles retain the application
capture size. Profiles without native cover support receive a compact cover that
is fitted to exactly 120x120 pixels and converted to grayscale with Lanczos resampling,
and is encoded as optimized single-channel JPEG. This file-tag representation is
independent of the iPodDB artwork representation.

## Consequences

Non-cover devices consume additional device storage for iOpenPod browsing, while
their firmware behavior is unchanged and unsupported. Native-capable profiles
retain their existing layouts and creation policy. Application-only artwork is
still bounded, fingerprinted, decoded lazily, and removed or retained according
to the existing Library draft and transaction rules. Rockbox-enabled Sync uses
additional media-file space for the embedded cover; a failed optional tag leaves
the media and iOpenPod artwork eligible to Sync with a warning.
