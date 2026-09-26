# ADR-0088: Edit Track classification in the metadata editor

- Status: Accepted
- Date: 2026-09-26
- Supersedes: ADR-0036's restriction on metadata-editor classification changes
- Extends: ADR-0026

## Context

The metadata editor exposes show, season, and episode fields but cannot classify a
retained video as a TV Show. ADR-0036 deliberately excluded `media_types` from
ordinary metadata edits while providing a dedicated Convert to Podcast workflow.
Users need other supported classification changes through the same editor.

## Decision

Expose a Media type selector under Options. Classification remains owned by a
dedicated Application Layer workflow; it does not become a generally editable
iPodDB metadata field or require Prepared Media.

The selector offers Music, Audiobook, and Podcast for Tracks currently classified
as audio, and Movie, TV Show, Music Video, and Video Podcast for Tracks currently
classified as video. The Application Layer validates that family for every selected
Track before publishing any edit. Documents and unclassified Tracks retain their
current values. A combined audio/video selection cannot change classification
together, but can still edit ordinary metadata.

Existing compound classifications appear as retained current values. Mixed values
and retained values remain unchanged until the user selects a replacement. Reset
restores the original selection. Applying classification, explicit metadata, and
artwork changes uses one revision-checked, unlocked Library Workspace operation,
which validates the whole batch and publishes at most one revision.

Reclassification changes only `media_types`. It preserves media bytes, codec facts,
paths, identities, and other metadata. Convert to Podcast remains the existing
separate action that also applies Podcast display, playback, and presentation
presets. iPodDB continues to derive native classification, video flags, and
Playlist consequences through the existing Library preparation and verification
path. Automatic or manual save follows the global Draft all changes setting.

## Consequences

- A video can become a TV Show while its show and episode metadata are edited in
  the same operation.
- The editor does not offer changes across audio, video, and document families or
  infer physical content from a newly chosen classification.
- No transcoding, media replacement, dependency, or direct device I/O is added.
- Regression tests cover bulk editing, retained and mixed values, reset,
  incompatible selections, revision/lock rejection, and verified database output
  without a media resource.

ADR-0036's retained-media ownership and Convert to Podcast behavior continue to
apply; only its exclusion of classification controls from the editor is superseded.
