# ADR-0117: Spill prepared Library content to Host storage

- Status: Accepted
- Date: 2026-10-05
- Extends: ADR-0030, ADR-0075, ADR-0076

The 512 MiB preparation thresholds protect retained memory; they are not iPod
format limits. Rejecting artwork prefixes or Photo batches at those thresholds
prevents otherwise valid changes. Truncating encoded media or thumbnail files
would corrupt content. Keep complete content and move overflow to private Host
files. Successful overflow is routine preparation and does not produce a warning.

iPodDB accepts path-free readable content and caller-provided append-only output
buffers alongside ordinary bytes. It hashes complete content and retained
prefixes in bounded chunks and reads individual thumbnail ranges for independent
verification. Its default buffers remain in memory. It neither imports Storage
nor opens paths; the application supplies Storage buffers that move to disk as
their aggregate memory budget is exhausted. Capture and generated artwork count
toward the same budget. Photo Sync uses a separate workspace with the same budget,
decoding one bounded image at a time and retaining overflow on disk. Remove both
Photo aggregate rejection checks.

The issued Library Review owns artwork and lyrics staging until Save, replacement,
disconnect, or failed preparation. Sync owns Photo staging through publication and
provenance recording. Storage checks content fingerprints before publication and
keeps the existing device preconditions and recoverable transaction. Cancellation
and failure close unfinished outputs and release their private files.

This trades Host disk space and additional I/O for bounded retained memory without
a batch-size restriction. These budgets do not bound total process memory: decoded
images, database models, and temporary working buffers are separate. Individual
image safety limits, native thumbnail shard sizes and offsets, and device staging
and recovery space checks still apply. No iPod lyric-text truncation policy is
introduced. Actual Host storage failures remain errors with actionable details.

## Budget and presentation update (2026-10-06)

The artwork/media capture workspace and the separate Photo Sync workspace each
retain up to 2 GiB before spilling to private Host files. This is a retained-data
budget, not a guarantee about total process memory. Routine disk staging does not
produce a user-visible issue; actual staging failures remain errors.

## Staging volume and crash cleanup (2026-10-14)

Complete prepared media, chaptered Album drafts, and content overflow use private
directories under the Host application cache by default. On Linux this is
`$XDG_CACHE_HOME/iopenpod/staging`, or `~/.cache/iopenpod/staging` when unset. The
system's default `/tmp` can be tmpfs: retaining a whole Sync there consumes RAM
and swap even though the Python objects and in-memory content budgets are bounded.
Media and content overflow must share the corrected directory policy.

Explicit `TMPDIR`, `TEMP`, and `TMP` overrides remain supported, in that order,
inside a private application subdirectory. An unavailable override fails instead
of silently falling back to another volume. The chosen cache or override must be
on a disk-backed volume to avoid tmpfs consumption. Complete preparations still
require Host disk space proportional to the batch. Sync continues to prepare the
complete desired Library before device publication, preserving complete-plan
validation and the recoverable Storage Transaction.

Each workspace holds an OS lock on an ownership marker for its entire lifetime.
Normal completion, cancellation, and failure remove it. Startup can reclaim
marked workspaces after a process crash only when their locks are available.
Creation and removal share a short root lock with cleanup so a second process
cannot interfere while an owner is creating or closing its workspace.
Cleanup does not recurse, follow links, remove unmarked legacy temporary
directories, or touch another running process's preparations. A matching filename
prefix alone does not establish ownership.
