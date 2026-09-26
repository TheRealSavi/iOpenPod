# ADR-0086: Prepare bounded stills for oversized Photos

- Status: Accepted
- Date: 2026-09-26
- Extends: ADR-0076 and ADR-0084

## Context

A 167 MiB animated GIF scanned successfully but failed Photo preparation because
the full container exceeded the 64 MiB in-memory original limit. The iPod Photo
viewer uses still renditions; retaining every animation frame is unnecessary for
that viewing copy. Raising the memory limit would leave large libraries fragile.

## Decision

Sources within the existing bound retain their original bytes. Larger image
containers are hashed through a seekable Storage stream, then their first display
frame is decoded into a PNG viewing copy. Existing decoding limits remain enforced;
the output is fitted within 4096 by 4096 pixels and remains under the per-image
bound. Thumbnail preparation and the batch bound apply to the resulting bytes.
Sync reports this conversion as information. The Host original remains unchanged;
the iPod copy does not retain animation.

Library Sync Helper v3 stores an optional Host content SHA-256 in Sync Details,
separately from the resulting iPod file's SHA-256. Subsequent matching checks the
original Host digest, so a converted Photo remains In sync while a changed Host
digest remains conflicting evidence. Readers retain compatibility with v1 and v2.

## Consequences

Large animated Photos can Sync without retaining the full animation in memory.
The source dimensions and encoded viewing copy remain bounded. This does not add
animated Photo playback or convert animations into iPod videos. Tests verify the
first-frame output, unchanged source, committed provenance, helper reload, and
repeat-Sync matching.
