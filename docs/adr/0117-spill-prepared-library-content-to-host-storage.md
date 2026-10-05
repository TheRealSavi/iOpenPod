# ADR-0117: Spill prepared Library content to Host storage

- Status: Accepted
- Date: 2026-10-05
- Extends: ADR-0030, ADR-0075, ADR-0076

The 512 MiB preparation thresholds protect retained memory; they are not iPod
format limits. Rejecting artwork prefixes or Photo batches at those thresholds
prevents otherwise valid changes. Truncating encoded media or thumbnail files
would corrupt content. Keep complete content and move overflow to private Host
files, with warnings that name the affected artwork file or Host Photo.

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
