# ADR-0120: Separate Track payload replacement from tag and artwork updates

- Status: Accepted
- Date: 2026-10-06
- Extends: ADR-0119, ADR-0066, and ADR-0076

## Context

Sync must distinguish changed media from changed tags and covers. Replacing or
transcoding unchanged audio is expensive and can lose quality. Scans already
calculate bounded Acoustic Fingerprints. A full encoded-stream checksum would
require another complete read and tool pass. The product explicitly favors the
existing approximate fingerprint comparison over that additional work.

## Decision

Compare the current Host Acoustic Fingerprint with the correlated iPod helper's
fingerprint. Different sequences request media replacement; equal sequences retain
the current media, even if Host size or modification time changed. Tags and artwork
are compared independently. Fingerprints remain bounded to the first 120 seconds
and are encoding-insensitive: this is an intentional approximation, not proof of
byte-identical audio or video. No full-stream checksum is calculated or stored.

Host Media Scan Cache v10 keeps the existing Acoustic Fingerprints, cached tags,
and independent folder-artwork catalog. Library Sync Helper v4 keeps existing
fingerprints, both Host and resulting iPod semantic tag digests, artwork provenance,
and the applied Rockbox tag policy. Changes to tags, artwork, media, and embedded
tag policy are independent Sync Plan intentions.

- A changed payload follows verified media preparation, new destination allocation,
  and recoverable replacement.
- Tags alone update iTunesDB. Unchanged ArtworkDB links and iTHMB bytes are retained.
- Changed or removed artwork updates ArtworkDB/iTHMB independently. Non-native
  devices retain the iOpenPod-only representation from ADR-0118.
- Lyrics always update the device file's tags, with Rockbox Metadata Support on or
  off. With Rockbox enabled, the same captured stream receives semantic tags and
  any changed embedded cover. Normalized desired Library values are used.
- Ordinary Library edits, including automatic saves, capture the Rockbox preference
  and derive retained-file tag updates from changed metadata or artwork assignments.
  Metadata-only edits preserve the embedded cover. Cover reassignment can use new
  pixels or a verified retained iTHMB range; clearing artwork removes its embedded
  copy. A preference change retires an uncommitted review. A tag preparation failure
  blocks the save instead of publishing database changes alone.
- Non-native Rockbox covers are exactly 120x120 grayscale JPEG; native profiles use
  the captured cover. The embedded representation is independent of iTHMB.
- Tag rewrites retain location, codec, duration, gapless facts, playback counters,
  pending scrobbles, checked state, and other device-owned fields. The verified
  rewritten file determines the new size in iTunesDB.
- iPodDB accepts explicit retained-file retag intent and requires verified lyrics
  and final file identity, even when the lyric text is unchanged. Storage captures
  the existing media once for transformation, verifies its fingerprint against the
  precondition, and publishes one write for all its tag edits. Large files spill to
  private Host disk; transformations perform the same read-back verification.
- Enabling Rockbox on previously synced Tracks requests missing embedded tags and
  cover without replacing audio or regenerating unchanged iTHMB files. Failed
  optional embedding leaves its policy unapplied so a subsequent Sync retries.
- Provenance is published only after the complete Library/media commit succeeds.
  Separate Host and iPod tag baselines prevent device normalization from producing
  recurring Updates, including after a Host timestamp-only change.

## Migration and unavailable evidence

V9 Host caches and v3 iPod helpers upgrade without rereading unchanged media or
covers. Their existing Acoustic Fingerprints and Photo evidence remain usable;
missing tag baselines remain unknown rather than being fabricated. No new media
fingerprint baseline is required. When either Acoustic Fingerprint is unavailable,
Sync conservatively proposes media replacement if Host size or modification time
changed. Unchanged Host facts retain the fast reuse path. This fallback also covers
silent video without usable acoustic evidence. Selected Updates still require the
usual preparation and source validation. A malformed cache is rejected; a malformed
device helper is preserved. Readers discard unused full-stream digest fields from
earlier development builds while preserving their other cached evidence.

## Consequences

Unchanged scans reuse cached fingerprints; changed media files recalculate only the
existing bounded acoustic analysis. Folder-cover changes require no media decoding.
The accepted tradeoff is that matching fingerprints can miss changes after the
analysis window, different encodings, and video-only edits with identical audio.

Same-size, same-mtime external edits remain outside the cheap cache gate. External
changes to iPod artwork bytes while retaining its artwork identity remain outside
this evidence. These caches do not authorize writes or replace Storage validation.
