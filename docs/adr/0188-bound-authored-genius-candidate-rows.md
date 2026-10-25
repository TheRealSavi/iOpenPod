# ADR-0188: Bound authored Genius candidate rows

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0178 and ADR-0179

## Context

A user reports noticeable pauses before an iPod selects the next native Genius
Track. Firmware timing has not been measured, but the authored graph supplies a
plausible source of excess work. The 256-candidate cap in ADR-0178 fills every
row to the Library size minus one on smaller Libraries. A 112-Track virtual
rehearsal consequently has 111 candidates per Track and 12,432 edges. Published
device captures contain 15, 19, 20, or 32 candidates per row. Those captures do
not establish a firmware limit. See the
[latency investigation](../research/genius-playback-latency-2026-10-24.md).

The 64-bit numeric magnitude of a Genius ID does not change the width of an
uncompressed candidate entry. Reassigning IDs would alter stable Track identity
and require coordinated changes in both Library and Genius companions. The two
artist and album spacing rules might also cause retries. Without timed hardware
evidence, changing the candidate count and rules together would obscure which
change affects the pause.

## Decision

Author at most 32 candidates per music Track. Keep the current audio ranking,
metadata fallback, Library-wide successor edge, stable Genius IDs, and native
spacing rules. Small Libraries continue to include every other music Track.
The 32-candidate cap is an Application Layer policy and is not described as a
firmware requirement or guaranteed performance fix.

The change reduces the maximum uncompressed similarity payload from 2,060 to
268 bytes per Track. For the 112-Track rehearsal, the generated candidate BLOBs
fall from 100,800 to 30,016 bytes while every Track remains reachable through
the successor edges. Structural reachability does not establish native playback
quality or next-Track latency.

## Consequences

Sync regenerates a smaller known Genius graph on supported iPods. Existing
Playlists, Mixes, and Unknown Data follow the preservation rules of ADR-0176 and
ADR-0178. Tests cover the cap, unique and valid candidates, graph reachability,
and both metadata and audio ranking paths. Native timing and queue behavior need
a controlled hardware comparison. If pauses persist, compare the same graph with
and without spacing rules as a separate experiment before changing their policy.
