# ADR-0271: Scale Genius analysis of staged Host audio

- Status: Accepted
- Date: 2026-11-15
- Amends: ADR-0183
- Amended by: ADR-0274 for one device read at a time

## Context

ADR-0183 limits Genius audio analysis to two concurrent Tracks to bound PCM memory
and avoid contending for a removable device's bandwidth. Admission was also
pairwise: both Tracks in a pair had to finish before the next pair started, so one
long Track idled the other worker.

Sync analyzes newly prepared Tracks from their staged Host captures on local
storage, after media preparation has finished. Those reads do not use the device,
and the CPU is otherwise idle at this stage. Decoding and profiling take roughly
0.5 seconds of CPU per typical Track, so a cold Sync of a few thousand Tracks spends
many minutes in this step while most cores are unused.

## Decision

Genius analysis uses a continuously refilled worker pool. By default it uses one
worker per two logical processors, bounded to between two and six workers. At most
two workers read from the device at once, preserving ADR-0183's device bound.
Staged Host captures may use every worker.

Host and device sources wait in separate queues, each in Library order. The next
Track admitted is the earliest admissible queue head, so a device Track waiting for
a read slot does not hold back staged Host captures. Outcomes are recorded and
progress is reported as Tracks complete; the analysis result remains in Library
order. Result collection, progress, and cache writes stay on the preparation
thread. Cancellation, skipping (ADR-0200), source validation, and the per-Track
decode limits are unchanged.

## Consequences

Cold Genius analysis of staged Host audio scales with available cores up to six
workers. Analysis of retained device media keeps the two-read bound.

Peak memory rises with the worker count. A worker holds at most about 80 MB of
PCM for a 15-minute Track, plus about 40 MB of retained mel blocks and bounded
per-block spectra. These buffers alone are not a process-memory upper bound:
temporary arrays, native libraries and decoding also contribute. An isolated
Windows profiler measurement with six 15-minute synthetic Tracks peaked near
1 GiB of resident memory, including Python and audio libraries but excluding
the full GUI and FFmpeg processes. A typical four-minute Track needs about
60 MB per worker. ADR-0273 records the accepted spectral-memory tradeoff.

Progress events no longer arrive in strict Library order. The active-Track list
can hold up to six entries.
