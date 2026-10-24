# ADR-0183: Bound concurrent Genius audio analysis

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0179

## Context

ADR-0179 established sequential acoustic analysis. Cold Sync then decodes and
profiles every uncached music Track before generating Genius relationships. Each
Track is independent, but serial decoding and profiling makes large cold Syncs
slow. Concurrent work increases PCM memory use and can contend for a removable
device's bandwidth.

## Decision

The Application Layer analyzes at most two music Tracks concurrently. Each worker
uses Storage's pinned, read-only source access and checks cancellation and source
identity before its result is accepted. The preparation thread collects outcomes
in Library order, updates progress, and writes the shared Host profile cache.
Cache access is synchronized while workers read it. A fatal source mutation,
disconnect, or cancellation stops unfinished workers before preparation proceeds.

The per-Track decode duration and PCM limits from ADR-0179 remain in force. Cache
entries and device source identities still cannot authorize mutation; the final
source checks before staging and publication remain required.

## Consequences

Two uncached Tracks may overlap in decoding and profiling, reducing cold Sync
latency when the device and Host have spare capacity. Peak PCM and intermediate
analysis memory can approximately double, and a slow device may see little gain.
The two-worker limit bounds that cost. Cache hits and optional failures retain
Library-order results and progress. A completed earlier profile remains reusable
when a later Track fails.
