# ADR-0123: Reuse bounded media scan analysis

- Status: Accepted
- Date: 2026-10-07
- Amends: ADR-0063's incomplete Track cache policy and ADR-0099's scan probe capture
- Extends: ADR-0065, ADR-0074, ADR-0076, ADR-0082, ADR-0084, and ADR-0120

## Context

Repeated scans spent work on unchanged cache serialization, repeated device checks,
and metadata whose optional Acoustic Fingerprint alone was missing. Before a
successful Sync, an iPod scan could not reuse its previous analysis because Review
must not publish the Library Sync Helper. Decimal Acoustic Fingerprints could also
exceed the 64 MiB cache limit at ordinary Library sizes. See the local measurements
in [Host Media Scan performance](../research/host-media-scan-performance.md).

## Decision

Retain successful metadata independently of optional acoustic analysis. Host Media
Scan Cache v11 records metadata completion explicitly, retries missing fingerprints
without parsing successful metadata again, and retries failed metadata even when a
fingerprint succeeded. Versions 9 and 10 migrate without rereading unchanged media.
Retain decoded records while the Storage cache-file revision is unchanged, and
write only changed catalogs. Revision checks are freshness hints, not source
authority. Failed writes remain retryable.

Host cache v11 and Library Sync Helper v5 store long Acoustic Fingerprints as
`u32z:` followed by base64 of zlib-compressed little-endian unsigned 32-bit values.
Short values retain their decimal representation. The conversion is lossless and
uses only the standard library. Readers accept prior decimal encodings; helper
versions 1 through 4 retain their existing migration rules. In particular, only
versions before 4 lack the committed tag and artwork baseline. Decoding checks the
250,000-value limit before expansion can become unbounded, and catalogs bound total
decoded acoustic text to 256 MiB as well as their existing 64 MiB encoded limit.
Writers enforce the same limits as readers. Invalid device helpers remain intact.

The Application Layer composes a separate **iPod Analysis Cache** in Host storage,
bound to physical-device and Volume identities. It stores only completed Track and
Photo analysis, keyed by persistent identity and Device Path and checked against
current size and filesystem-aware modification time. It never contains Sync Details
or supplies committed provenance. The device helper remains the authority for those
details. The Host cache checkpoints changed analysis every 30 seconds and on scan
exit, including cancellation. Its record and byte limits evict oldest analysis;
cache loss or corruption simply requires analysis again. Pre-Review scans still
perform no device helper writes, including on read-only iPods.

Bound Host directory concurrency to four workers and inspection to eight workers,
with bounded pending work, deterministic results, and progress delivered by the
owning scan thread. Both selected-tree passes obtain fresh observations. Preserve
selection overlap rules, explicit external Playlist review, Storage path and
identity checks, and final Sync source revalidation. Resolve fpcalc lazily once
per scan, including missing-tool results; a later scan retries discovery.

For iPod cache misses, overlap one Storage capture with one acoustic calculation,
retaining at most two temporary captures. Device reads remain serialized through
the current Filesystem Session. Recheck file facts after content analysis, abort
on session failure, and close all captures on completion or cancellation. Cached
analysis needs one current stat, without repeating it when no content was read.
Comparing already-observed modification times is arithmetic using the session's
filesystem type, while actual filesystem operations retain connection validation.

Selected Host videos may obtain descriptive FFprobe metadata through a pinned,
seekable Storage input without a whole-file capture or content digest. The typed
result cannot stand in for captured import/preparation evidence. Output bounds,
protocol restrictions, cancellation, and source checks remain in Storage. Approved
external Playlist references still require their reviewed private captures.

## Consequences

Warm scans avoid cache rewriting and repeat decoding; first scans can overlap
independent directory requests and device capture with acoustic calculation.
Directory concurrency can be reduced for a constrained mount. Optional fingerprint
failures remain retryable, so installing a tool or repairing media takes effect on
the next scan. Cache reuse still relies on cheap file facts and cannot detect edits
that deliberately preserve them; caches never authorize writes. Real NAS and iPod
timings still depend on filesystem latency and decoder performance. Native device
identifiers may change when disks are renumbered; that conservatively starts a new
Host analysis cache even when the same iPod returns.
