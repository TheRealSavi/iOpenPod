# ADR-0084: Keep optional media analysis out of Sync gates

- Status: Accepted
- Date: 2026-09-26
- Extends: ADR-0063, ADR-0065, ADR-0066, ADR-0076, ADR-0082 and ADR-0083
- Amends: ADR-0076 and ADR-0081's requirement that every Sync needs fpcalc

## Context

The owner requested a scan and Sync workflow that continues through recoverable
file problems and explains its current work. Acoustic matching, optional artwork,
and incidental container diagnostics were being treated as prerequisites for
otherwise valid media. Review allowed an explicit Add without a fingerprint, but
execution rejected that same selection.

## Decision

Host Media Scan retains readable media when acoustic analysis is unavailable.
An explicit Add requires verified playable media, not an Acoustic Fingerprint.
Ambiguous matches still cannot authorize an automatic Update or Remove. Proven
Sync Details are matched before optional acoustic evidence is considered.

Library Sync Helper format v2 permits an empty acoustic fingerprint only alongside
committed Sync Details. It continues reading v1 helpers. This records successful
copies of short or silent media without inventing matching evidence, and permits a
later scan to recognize the same Host path. Older applications cannot read v2.

FFmpeg and FFprobe are required only for incoming Track preparation. Missing tools
skip that portion of a mixed Sync; Photos, explicit removals, and independently
safe Playlist work may proceed. fpcalc remains a user-installed matching tool.
No executable is installed or downloaded automatically.

Storage offers explicit best-effort directory enumeration. It reports unavailable
entries and changing contents while continuing to verify directory identity and
reject links or replacement directories. Host scanning handles inaccessible
subfolders independently and publishes completed inspections as they finish.

FFprobe's successful, structured output is usable even when its diagnostic stream
mentions malformed optional metadata, such as a stale QuickTime chapter reference.
Its nonzero exit, invalid output, resource bounds, and subsequent media decode
verification remain failures. Diagnostics are retained in debug logging.

Embedded artwork is read through a Storage-owned seekable stream. Image payload
and decoded dimension limits apply to the image, not the enclosing audiobook.
Ordinary missing tags use filename/basic facts. WAVE and AIFF ID3 text frames are
recognized even when Mutagen does not return easy-tag names. Host scan cache v8
invalidates older metadata projections.

Audio-only containers follow the same default-stream selection as video. A
compatible selected audio stream is remuxed without re-encoding when possible.
Duration checks and stream metadata refer to the selected edition. Decode
verification covers playable streams rather than attached cover images.

Progress identifies reading, inspection, conversion, and verification before they
finish. Expected conversion consequences are informational; repeated result
messages are grouped. A changed Host file that was already In sync cannot prevent
independent media changes; affected Playlist reconciliation is conservatively
skipped. Changed incoming media remains excluded before publication.

## Consequences

Scan results can have incomplete matching evidence and metadata. Explicit Adds
without acoustic identity can create duplicates if an existing iPod copy has no
prior Sync Details; no duplicate-free correlation is claimed. Known prior paths
avoid repeating an already committed Add on subsequent Syncs.

Unsafe device state, disconnects, unverified prepared output, and insufficient
transaction space still stop publication. Best-effort preparation does not weaken
the Storage Transaction or give stale scan facts write authority.
