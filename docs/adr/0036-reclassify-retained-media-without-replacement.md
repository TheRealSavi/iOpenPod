# ADR-0036: Reclassify retained media without replacement

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0026 and ADR-0034

## Context

The Track context menu needs the Original iOpenPod's Convert to Podcast action.
That action changes firmware-facing classification and presentation fields but does
not alter the retained audio or video bytes. The Library field policy previously
grouped `media_types` with codec facts that require Prepared Media, which would
incorrectly turn this metadata-only reclassification into a media replacement.

The semantic `MediaType` values still need a narrower owner than the general
metadata editor. Arbitrary form edits could otherwise claim that audio is video or
that an incompatible file has another content type without a dedicated workflow.

## Decision

Classify `media_types` as Track classification rather than Prepared Media content.
Changing classification on an existing Track does not require Prepared Media;
adding a Track and changing codec-owned fields still do. Classification is not a
general editable metadata field. A dedicated Application Layer workflow owns each
supported transition.

Convert to Podcast follows the Original iOpenPod's semantic behavior. It chooses
audio or video Podcast classification from the retained Track, enables Podcast Now
Playing, Skip When Shuffling, and Remember Playback Position, aligns played state
with play count, and fills missing show/category presentation fields with stable
fallbacks. iPodDB reconciles the Podcasts Playlist and writes and verifies the
result through the existing Library Draft review. The operation never transcodes or
replaces the media file.

## Consequences

- Podcast conversion is a reversible Library Draft edit and remains subject to
  Review Changes and Save to iPod.
- iPodDB can rewrite the native media-type classification without demanding an
  unrelated media resource.
- Future classification actions require dedicated Application workflows and tests;
  the metadata editor remains unable to change `media_types` directly.
- Transcoding, file replacement, and conversion to a single chaptered Track remain
  separate workflows.
