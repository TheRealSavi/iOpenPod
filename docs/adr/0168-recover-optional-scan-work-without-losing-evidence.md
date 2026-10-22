# ADR-0168: Recover optional scan work without losing evidence

- Status: Accepted
- Date: 2026-10-22
- Extends: ADR-0065, ADR-0082, ADR-0123, ADR-0156, and ADR-0162

## Context

Fault-injection tests found that a temporarily unreadable Playlist could remain
empty across subsequent Host Media Scans. An unreadable Photo produced a cache
record that the next scanner rejected, discarding reusable analysis for healthy
files. An inaccessible Library Sync Helper aborted an iPod Media Scan even though
the helper is optional analysis and provenance evidence. Interrupted directory
iterators also discarded already inspected entries.

Device whole-file reads continued until EOF, unlike the bounded Host reads in
ADR-0162. A growing file could extend the operation indefinitely, and a provider
returning EOF early could supply incomplete bytes while reporting unchanged file
facts. These operations serve both scan analysis and other Storage clients.

## Decision

Host Media Scan Cache v16 distinguishes completed Playlist parsing from failed
reads. Completed parser warnings remain reusable; failed reads are retried on a
later scan. Readers retain supported v9-v15 media records. Existing pre-v14
Playlist migration rules remain; v14-v15 Playlists with warnings are reparsed once
because their completion cannot be established. A Photo record with an absent
content digest represents incomplete analysis and is retried, without invalidating
unrelated cached media. Invalid nonempty digests remain rejected.
Cached embedded-artwork observations must also match their Track's path, size,
and modification time; inconsistent cache documents are rebuilt before projection.

Host inspection retains completed per-file results in its disposable cache at
completion checkpoints spaced at least 30 seconds apart, and when inspection
exits, including cancellation. A later scan obtains
fresh source observations before reuse. Unfinished work is not retained, and
cancellation publishes no Library Snapshot. Cache write failures remain optional
and retryable under the existing cache policy.
The same checkpoint policy covers accepted external Playlist media after its
private capture and reviewed observation have both been validated. Cached analysis
does not retain approval for a later scan. Lazy external artwork reads also retain
the original approved observation.

Filesystem modification times remain signed integers throughout Host caches,
iPod analysis, and committed Sync Details. Valid pre-1970 source timestamps are
neither rejected nor clamped. Host path-derived identities encode surrogate code
points losslessly, and cache JSON escapes them without changing the canonical
encoding of ordinary Unicode paths.

Best-effort Host directory enumeration may restart once on an iterator I/O failure,
inside the same pinned directory access. A successful restart replaces the partial
catalog with its current entries; repeated entries do not duplicate progress.
Persistent failures retain inspected entries with a diagnostic;
directory identity and no-link validation still gate publication. Strict callers
retain their fail-on-error contract. Cancellation is never an enumeration failure.

An iPod Media Scan may retry one failed Library Sync Helper observation for an I/O
or concurrent-change failure. If the helper remains inaccessible, media analysis
continues without its cached evidence or Sync Details. The existing helper remains
protected from replacement. Session invalidation and disconnect still stop the
scan. Publication and retained-file mutation retain their strict helper reads and
revision preconditions; this fallback applies only to analysis.

Storage whole-file device reads and fingerprints now use the size observed on the
opened descriptor as their read boundary, below buffering. They reject a caller's
size limit before reading, reject premature EOF, and compare final file facts to
reject growth or other changes. They check session activity throughout and after
reading. This extends ADR-0162 to these device reads without changing mutation
authorization or substituting cached evidence for content verification.
Device-to-Host captures use the same observed-size boundary and preserve caller
cancellation exceptions. Whole-file reads also validate the final named file.
The shared device read opener uses Storage's existing ancestor and leaf pinning
for the entire stream lifetime, closing the gap between path validation and open.
This restores the existing containment contract rather than authorizing new paths.

Optional image inspection preserves image-decoder pixel limits. An over-limit
Photo or cover becomes an item diagnostic; independent media remains available and
another valid folder cover can be selected. Completed scans display both Host and
iPod diagnostics in Select Media and Review. iPod progress is coalesced before
queued GUI delivery, preserving phase boundaries and final totals.
Cancellation also suppresses results, errors, and progress already queued for GUI
delivery while retaining the device reservation until the worker completes.
Native serial analysis reobserves a Track after waiting for the preceding decode;
session invalidation during any media-analysis phase stops the scan instead of
becoming an ordinary per-item diagnostic.

Host scans also exclude `.AppleDouble` companion metadata directories, matching
the Original iOpenPod baseline. This applies to selected paths, ordinary and
opt-in linked traversal, and Playlist references, while ordinary hidden media
folders remain eligible.

## Consequences

Transient failures can recover within a scan, and incomplete cached items can
recover on later scans without repeating healthy media analysis. Ordinary scans
incur no extra directory pass or helper read. Recovery does not invent Sync
history, overwrite an unreadable helper, follow unauthorized links, or conceal
unavailable files.

Tests use temporary Host trees, virtual iPod Volumes, controlled filesystem
failures, and bounded progress clocks. Native USB and network latency still need
measurement on the affected hardware. Blocking operating-system calls can delay
cancellation; unreadable content and absent devices cannot be repaired by treating
them as successful reads.
