# Host Media Scan performance

Investigation date: 2026-10-07. Initial baseline: `b378219` (2.0.6).
The later cache and concurrency measurements use `564fc006` as their baseline.

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
The initial optimization retained ADR-0063's complete reinspection on a missing
Acoustic Fingerprint. ADR-0123 subsequently separates successful metadata from
optional acoustic retries, as described below.

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

### Opt-in symbolic links

ADR-0132 adds per-folder symbolic-link traversal while retaining the normal scan
path. A 2026-10-08 Windows operation-count check used 40 album directories with
20 WAVE Tracks each, 40 directory aliases, and a link back to the selected root in
each album. With link following either disabled or enabled, the warm scan reused
all 800 Tracks, inspected none, made 82 directory listings across both enumeration
passes, and opened no media streams. These are local operation counts, not NAS
timings. Regression tests also verify that hard links are inspected once and that
ordinary ancestor probes are shared within one resolution pass without bypassing
read-time validation.

### Inspection and ordinary traversal

Inspection uses a continuously replenished queue with at most four pending tasks
per worker and at most eight workers. Completed results are published by the owning
scan worker and the final records remain sorted. A slow file no longer prevents
later files from starting merely because they belong to another batch. Waiting
for completions checks cancellation regularly; cancellation also cancels queued
tasks and signals running inspections through their checkpoints. Tests hold the
first file open until a file beyond the former batch boundary finishes, so this
behavior does not depend on timing-based speed assertions.

The initial change kept directory enumeration serial. The scanner visits overlapping selections
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

The initial change retained the existing Acoustic Fingerprint retry policy and
end-of-scan persistence. The following changes extend that work.

## Cache reuse and bounded concurrency

ADR-0123 introduces independent metadata/acoustic reuse, compact fingerprints,
dirty-only cache writes, revision-bound decoded caches, four directory workers,
and a Host-side iPod Analysis Cache. iPod scans overlap one serialized device
capture with one decoder and keep at most two temporary captures. Descriptive
video probing uses a pinned, seekable input without copying the entire Host file.
All selected-tree passes and Storage identity/path checks remain in place.

The local fixture has 1,000 WAVE Tracks across 50 albums and a virtual iPod with
200 files of 64 KiB each. Fingerprinting is stubbed with a 948-value decimal
sequence. Both versions perform the same 102 Host directory listings and return
2,100 entries across two passes. Measurements exclude native decoding, GUI work,
NAS requests, and physical USB latency. Wall times are illustrative, not a device
performance guarantee; operation counts are the more stable comparison.

| Measurement | Before | After |
| --- | ---: | ---: |
| Warm Host scan, 1,000 Tracks | 0.688 s | 0.231 s |
| Warm Host cache writes | 2 (22.0 MB total) | 0 |
| Warm Host progress events | 1,009 | 11 |
| Host cache size | 11.0 MB | 2.41 MB |
| Metadata parses when retrying 20 missing fingerprints | 20 | 0 |
| Cached iPod scan, 200 Tracks | 0.409 s | 0.167 s |
| Cached iPod stat calls, including helper | 401 | 201 |
| Cached iPod Volume reinspections, including helper | 804 | 204 |
| Repeat iPod scan before Sync | 0.947 s | 0.120 s |
| Repeat pre-Sync device copies / acoustic calculations | 200 / 200 | 0 / 0 |

The first Host scan writes its cache once instead of twice. A new scanner instance
reads and decodes the cache once: the restarted warm Host run took 0.373 seconds.
The 6,500-record capacity probe previously exceeded 64 MiB for both caches; it now
fits in 15.6 MB for Host metadata and 12.8 MB for the helper. Compression depends on
the values: this sequential stub compresses particularly well. A separate test
with mixed unsigned 32-bit values verifies exact round trips below 60% of decimal
text size. Catalog limits remain enforced on both encoded and decoded data.

These decoder-free fixtures do not establish a first-scan speedup: the measured
Host first scan changed from 1.60 to 1.76 seconds and the virtual iPod first scan
from 3.50 to 4.09 seconds. They cannot exercise useful copy/decode overlap with an
instantaneous stub, and local file timings include cache and scheduling noise.
Regression tests instead require later device copying to proceed while the first
decoder is blocked, and require independent directory listings to overlap without
exceeding the configured worker bound. Real first-scan timing still needs a
representative device or mounted library.

A controlled latency experiment isolates directory overlap: 400 Tracks in 40 album
directories, three repetitions, and an added 20 ms delay per listing. Median first
scan time with one versus four workers was 2.287 versus 0.997 seconds; warm time was
1.829 versus 0.544 seconds. All runs made 82 listings, returned 880 entries, and
produced identical Track counts without issues. This demonstrates tolerance of
simulated latency, not a measured WebDAV speedup. A flat 400-Track directory with
no added latency had about 3.5 ms of extra warm-scan overhead with four workers,
because there were no independent directory listings to overlap.

Canonical raw fingerprint validation also avoids rebuilding unchanged decimal
strings. Across 24 distinct mixed 948-value sequences, the local median fell from
208 to 85.8 microseconds per fingerprint. Leading-zero legacy values still
normalize, and unsigned range, syntax, and value-count checks remain enforced.

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
explains why unchanged Tracks may still need acoustic retries. Successful metadata
is retained during those retries under ADR-0123.

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

Metadata enumeration now overlaps up to four directories, and Storage still
validates ancestors. Measure actual mount request counts before changing path checks
or increasing concurrency.
The extra selected-tree pass after external Playlist review remains intentional.

A direct remote directory-metadata adapter could avoid mounted-filesystem round
trips, but it would need an explicit design for source identity, authorization,
credentials, timestamp precision, and subsequent reads through Storage. No remote
backend, weaker path checks, cache expiry policy, or skipped final traversal is
introduced by this optimization.
