# ADR-0157: Review explicit media stream selection

- Status: Accepted
- Date: 2026-10-19
- Extends: ADR-0031, ADR-0067, ADR-0076, ADR-0083, and ADR-0120
- Amended by: ADR-0158 for durable choices, applied-choice receipts, and video matching
- Amended by: ADR-0160 for automatic text conversion and readable subtitle recovery

Sync now offers per-Track **Choose streams** in Select Media. A Media Stream
Selection chooses one motion-video stream, one audio stream or silence for video,
and any supported separate subtitle and caption streams. Audio-only sources require
one audio stream. Automatic selection retains ADR-0083's existing behavior.
Choices belong to the current Sync Selection and reset on a new scan or Active
iPod; they are not Host metadata or persistent matching evidence.

The chooser inspects only the requested Host source, in a cancellable background
job using Storage's pinned metadata probe. It checks the scan's file facts before
inspection and the file's identity and facts afterward. This avoids expanding the
scan cache or copying entire videos merely to open an editor. Selected immutable
stream facts accompany their indices into the Sync Plan; preparation checks them
against the captured Media Inspection. Missing, changed, or unsupported choices
fail explicitly rather than falling back to another language or edition.

Applying explicit choices requests media preparation even when Acoustic
Fingerprints match. A safely correlated In sync Track becomes an Update with media
replacement; Adds keep their existing identity rules. Stream choices cannot resolve
ambiguous correlations, authorize unrelated removals, or override final Review
exclusions. Restoring automatic selection restores the original comparison action.
Plan validation reconstructs the permitted change from the original comparison.
Ordinary verified preparation and transactional publication remain mandatory.

Preparation maps explicit indices, makes the sole audio/video streams default,
and retains stream tags and representable dispositions. Supported `tx3g` text and
`c608` captions can be retained together. Common embedded text subtitles (SubRip,
ASS/SSA, WebVTT, plain text, and MOV text) can become dimensioned `mov_text` when
the Device Profile supports it. Formatting can be simplified. Caption output uses
the MOV muxer and explicitly tags text as `tx3g`; text rectangles are adapted when
the selected output video has different bounds. Prepared output is checked for
the requested stream counts as well as compatibility, duration, and decoding.
Bitmap subtitles, unsupported caption formats, and external subtitle files are not
converted by this workflow. Captions carried inside a video bitstream are not
separate selectable streams and stay subject to that video's preparation.

Original iOpenPod's `origin/1.x` transcoder maps the first audio/video streams and
provides the MOV-caption handling baseline. This adds explicit intent without a
runtime dependency on the Original project or a new dependency. Real FFmpeg tests
cover alternate streams, silence, text conversion, mixed text/captions, and actual
Sync publication; Qt tests cover selection, cancellation, stale sources, and Review.
Physical iPod subtitle rendering remains device- and firmware-dependent.
