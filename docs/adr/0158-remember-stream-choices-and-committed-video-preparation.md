# ADR-0158: Remember stream choices and committed video preparation

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0120 and ADR-0157

## Decision

Media Stream Selection is durable user intent for one normalized Host file path.
Store it atomically in the Host configuration directory, separately from disposable
analysis caches. Applying a choice saves it before the dialog accepts; cancelling
the dialog does not save. Sync cancellation, deselection, unavailable folders,
rescanning, application restart, and changing Active iPod do not erase choices.
Restoring automatic selection removes the explicit preference. File moves require
new choices because bounded audio evidence cannot safely transfer visual intent.

Retain the complete immutable selected stream facts with their indices. A versioned
JSON codec preserves rational timing exactly. Preparation still checks those facts
against the captured source and the current Device Profile. Stale or unsupported
choices never silently select another stream; the chooser lets the user correct
them against fresh inspection. A failed save retains prior intent. Unreadable
preferences are preserved and visibly prevent Sync until recovered and rescanned.

Library Sync Helper v6 adds an optional SHA-256 of the canonical selected-stream
document. This records successful preparation, not media identity. Versions 1–5
remain readable without this field; no analysis is repeated just for migration.
Successful publication records the digest, metadata-only updates retain it, and
failed or excluded operations do not advance it. Desired and applied choices are
compared when creating Review: equal choices keep the original action, different
choices request one media replacement. Removing a choice also requests replacement
once when the current copy was prepared with an explicit selection. Plan validation
reconstructs these changes from captured comparison evidence.

## Video identity and cost

The first 120 seconds of default audio cannot prove that a movie's picture,
alternate audio, or subtitle tracks match. Unchanged sources and established Sync
associations retain the existing fast cache path. Changed video file facts, or
changed source facts for an explicitly prepared Track, request media preparation
even when default audio matches. This conservatively includes metadata-only edits
inside a video container, avoiding another whole-file read to distinguish them.

For video without an established association, equal acoustic evidence offers a
candidate for explicit matching in Review, including one-to-one candidates. It
does not automatically declare the video In sync. An explicit video match prepares
the Host media before recording its provenance. Audio and video remain separate
candidate families. Silent new videos can be explicitly added; committed Host-path
provenance handles later scans. Stream preferences never resolve ambiguous matches
or independently authorize removal.

This extends Original iOpenPod's first-stream preparation baseline without adding a
dependency or hashing whole videos during scans. It applies by observed video
content and Device Profile capability, independently of Movie, TV Show, Music Video,
Video Podcast, or combined audio/video classification. Existing verified output,
metadata/artwork handling, and Storage transactions remain mandatory. Bit-identical
output across different FFmpeg versions is not promised. Same-size, same-mtime
external source edits remain outside the cheap scan cache gate; physical subtitle
and caption rendering still requires device-specific playback validation.

## Verification

Real FFmpeg and virtual-device tests cover saved silent-video choices through
publication, restart, rescan, metadata updates, restoring automatic preparation,
and subsequent unchanged plans across the video classifications. Further tests
cover alternate audio/video, mixed text/captions, missing sources, corrupt
preferences, failed saves, stale-choice correction, legacy helpers, ambiguous
matching, and changed video sources with unchanged audio evidence.
