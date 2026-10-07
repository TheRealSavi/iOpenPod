# Host Media Scan performance

Investigation date: 2026-10-07. Baseline: `b378219` (2.0.6).

## Finding

The reported workload is approximately 2,000 previously scanned Tracks on a NAS
served by copyparty and mounted through WebDAV on an M1 Mac. The mount client,
configuration, HTTP request counts, and actual stage timings are not yet known.
The reported one-to-two-hour duration is not evidence that the NAS disks are slow.

`HostMediaScanner.scan()` previously enumerated selected media, independently
enumerated each audio/video directory for folder artwork, inspected cache misses,
and repeated both enumerations. An ordinary album directory therefore underwent
four metadata sweeps even when every Track reused its Host Media Scan Cache entry.
Storage already uses `os.scandir()` and obtains size and modification time from the
same stat result. Combining separate size/time calls is not an applicable fix.

The scanner now retains plausible folder-cover `HostDirectoryEntry` observations
from media discovery and reuses them during that pass's artwork discovery. Empty
and unavailable listings are retained as empty results instead of retried for
artwork. Photos need not be enabled to discover covers. Every final enumeration
starts with a new directory catalog, so covers added, changed, removed, or replaced
by a higher-priority filename are still reconciled.

Only cover candidates and per-directory counters are retained in addition to the
existing media observations; full listings of unsupported files are not kept for
the artwork pass. Explicit file selections still use a separate parent listing
when media discovery did not enumerate that directory. This does not add sibling
media to the selected catalog. Approved external Playlist references retain their
embedded-artwork-only access policy.

This is an implementation optimization within ADR-0063, ADR-0074, ADR-0082, and
ADR-0084. It preserves both selected-tree passes, best-effort diagnostics,
cancellation, Storage identity/path/read checks, and Sync source revalidation.
Missing Acoustic Fingerprints still cause reinspection on the next scan, as
specified by ADR-0063; cached metadata alone does not establish a complete cache
hit. Retrying optional analysis separately from metadata would require a separate
cache policy change.

## Local operation-count comparison

A synthetic fixture contained 100 album directories, each with 20 WAVE Tracks and
one PNG cover. Each version used a populated cache with valid stubbed Acoustic
Fingerprints. Both reused all 2,000 Tracks and inspected zero files. Counts wrap
Storage's actual `list_entries()` calls over local files, including both scan
passes and ordinary completion without external Playlist review.

| Measurement | Baseline | Shared observations |
| --- | ---: | ---: |
| Directory listings | 402 | 202 |
| Returned entries across listings | 8,600 | 4,400 |
| Track entries across listings | 8,000 | 4,000 |

Each returned entry receives one child metadata lookup in the current Storage
implementation. These counts exclude ancestor/identity checks and reads. They are
application operation counts, not HTTP request counts. They demonstrate removal of
half the Track metadata lookups for this layout, not a measured NAS speedup or an
assurance that an hour-long scan will become fast. Mount caching can make the
relationship between filesystem calls and network requests very different.

With ten unsupported text files added to each album (1,000 extra files), the
baseline returns 12,600 entries across 402 listings. Shared artwork observations
plus filename filtering return 4,400 entries across 202 listings. Both versions
still reuse all 2,000 Tracks. Storage tests separately verify that rejected files
do not receive the explicit child stat call. A mount without directory-entry type
information may still need metadata to determine whether an excluded name is a
directory.

## Additional scan improvements

Inspection uses a continuously replenished queue with at most four pending tasks
per worker and at most eight workers. Completed results are published by the owning
scan worker and the final records remain sorted. A slow file no longer prevents
later files from starting merely because they belong to another batch. Waiting
for completions checks cancellation regularly; cancellation also cancels queued
tasks and signals running inspections through their checkpoints. Tests hold the
first file open until a file beyond the former batch boundary finishes, so this
behavior does not depend on timing-based speed assertions.

Directory enumeration remains serial. The scanner visits overlapping selections
once per directory per pass. At each path it combines the media types from every
applicable selection; a nonrecursive selection only applies at its own root.
Processing ancestor selections first avoids relisting a selected child directory.
Tests cover both selection orders and all parent/child recursion combinations.
Explicit files already observed in a selected folder reuse those observations,
including when the folder's media-type choices would otherwise exclude that file.

Storage accepts an optional filename predicate and a directory-inclusion flag.
The Application Layer supplies selected media names and potential cover names;
Storage retains all path, identity, and no-link validation. Irrelevant names are
skipped before requesting detailed metadata where directory-entry type information
allows it. Nonrecursive selections need no directory-type lookup for rejected
names. Existing Storage callers without a filter retain full enumeration.

Storage can report provisional entries during a listing for progress. These do not
enter the media catalog before the complete listing passes its directory checks.
Discovery and final verification show folders visited, media files found, and the
current path while enumeration is running, including within a large directory.
Updates are limited to ten per second with an unconditional final count. The total
remains unknown during traversal, so the progress bar is indeterminate. Spanish and
German catalogs include both new progress templates. Blocking filesystem calls can
still delay progress and cancellation until control returns to the scanner.

Acoustic Fingerprint retry policy and end-of-scan cache persistence are unchanged.

## Diagnosing the affected mount

The application log now records these independently timed stages for each pass:

- `Host Media Scan enumeration`: elapsed seconds, directory listing attempts,
  returned entries, selected files, and issues. A start message precedes traversal.
- `Host Media Scan folder artwork`: elapsed seconds, audio/video directories,
  reused listings, fallback listings, and usable covers. Fallbacks normally mean
  explicit files whose parent directory was not enumerated.
- `Host Media Scan inspection`: elapsed seconds, reused and inspected files, and
  Tracks without an Acoustic Fingerprint. Inspection includes metadata, embedded
  artwork, and fingerprint work, so this timing alone cannot separate them.

For a fully cached folder scan, expect `inspected=0` and `fallback_listings=0`.
Slow enumeration with those values points toward filesystem metadata and directory
validation work. Slow inspection with cache misses needs investigation of content
reads or fingerprinting. A repeated nonzero `tracks_without_fingerprint` count
explains why unchanged Tracks may still be reinspected.

Collect the macOS version, how WebDAV is mounted (Finder, rclone, or another
client), relevant mount metadata-cache settings, copyparty version, HTTP/HTTPS and
proxy arrangement, and directory layout. Redact credentials and private addresses.
Compare a small representative directory through the mount with the same files
on local storage, and correlate a scan with copyparty request counts if available.

For a mount-only metadata comparison, acquire **fresh** `DirEntry` objects for
each repetition, or call `os.stat(path, follow_symlinks=False)` on every repetition.
Calling `entry.stat()` twice on the same `DirEntry` measures Python's cached result
the second time; it does not establish that macOS cached the remote metadata.
On Unix the initial `DirEntry.stat()` requires a system call, whose network effects
depend on the mount. See the
[Python 3.12 directory-entry documentation](https://docs.python.org/3.12/library/os.html#os.DirEntry.stat).

## Remaining work

Metadata enumeration remains serial, and Storage still validates ancestors.
Measure those costs before adding directory concurrency or changing path checks.
The extra selected-tree pass after external Playlist review remains intentional.

A direct remote directory-metadata adapter could avoid mounted-filesystem round
trips, but it would need an explicit design for source identity, authorization,
credentials, timestamp precision, and subsequent reads through Storage. No remote
backend, weaker path checks, cache expiry policy, or skipped final traversal is
introduced by this optimization.
