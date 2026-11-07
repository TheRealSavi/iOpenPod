# ADR-0227: Prefetch bounded Phase audio inputs

- Status: Accepted
- Date: 2026-11-02
- Extends: ADR-0210 and ADR-0226
- Supersedes: ADR-0210's coordinator-only device reads

Phase preparation previously hashed each retained device Track, decoded it from
the device, then hashed it again. These serial reads leave analysis waiting on
removable storage between Tracks. The user requested copying upcoming songs while
the current song is analyzed.

## Decision

One preparation-owned reader captures compressed audio through
`FilesystemSession.copy_to_host`. Its returned fingerprint supplies both the
content-cache key and the transaction precondition, replacing the separate first
hash pass. The existing configured FFmpeg decoder reads the captured Host file.
Analysis starts when the first capture is ready; it does not wait for the queue
to fill. Eligible Tracks retain Playlist order and persistent-ID deduplication.
Incoming prepared Host media keeps its existing verification path.

The reader admits the current input and at most five upcoming inputs. Retained
compressed content is limited to 256 MiB, including the current capture. It does
not predecode additional songs or create additional model workers. The byte limit
can reduce the number of queued songs. Individual files over the limit use the
existing direct device decode path, after earlier captures have drained. A Host
disk-full or quota error during workspace creation or capture disables further
copies for that preparation and uses the same serial path. Other errors propagate.

The limit describes retained audio, not total filesystem allocation. Storage's
atomic Host publication may briefly require a second copy where hardlinks are
unavailable; an input growing during capture is rejected at the next bounded copy
checkpoint. The selected Host staging volume and marked crash-cleanup policy are
unchanged. Each consumed file is removed, and the reader is stopped and joined
before its flat workspace closes.

## Verification and lifetime

The reader never invokes application cancellation or progress callbacks. It checks
its stop signal and Filesystem Session state between copy chunks. The coordinator
checks user cancellation while waiting and during analysis; a reader failure also
reaches those checkpoints. Cancellation, disconnection and analysis failures stop
admission and drain the reader before returning.

After successful analysis or chart reuse, the original device file receives the
same complete fingerprint check as before. A shared I/O guard serializes this
full-file verification with background copies, giving verification priority over
starting another capture. An already active copy may finish first. The optional
checkpoint on `FilesystemSession.fingerprint` makes these hash reads cancellable
between chunks. Failed or cancelled analysis skips post-analysis validation so it
does not mask the original exception. Device transaction preconditions remain
mandatory; Host captures never authorize device writes on their own.

Private capture identity is checked around use, and source identity changes
between admission and capture are rejected. The queue also checks sources whose
charts are reused, retaining content-based cache behavior. This can add temporary
Host writes on a fully cached preparation; it avoids a separate device hash before
deciding whether analysis is needed.

All analysis parameters, output ordering and algorithm/cache identities remain
unchanged. This scheduling change introduces no dependency, setting or download.
The [measurement report](../research/phase-input-prefetch.md) records observed
timings, output comparisons and acceptance limits.
