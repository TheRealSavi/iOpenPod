# ADR-0199: Make Sync Genius analysis optional

- Status: Accepted
- Date: 2026-10-27
- Extends: ADR-0178 and ADR-0184

## Context

ADR-0178 made native Genius generation part of every Sync on a supported iPod.
Audio profiling and candidate ranking can add significant time even when a user
only wants to synchronize media. Settings already supports Host defaults and
portable iPod overrides for optional Sync work.

## Decision

Sync exposes an **Analyze for Genius** setting, enabled by default so existing
behavior continues. It can be overridden for an individual iPod. The effective
value is captured when Sync starts. When off, Sync does not request Genius graph
regeneration or automatic Genius Mix rotation, and therefore does not decode
music for Genius or rank Genius candidates. Ordinary Library preparation still
preserves and reconciles retained Genius data according to its existing rules.
Turning the setting back on regenerates the graph from the current music Library.

## Consequences

Users can avoid Genius analysis time during routine Sync. New music added while
the setting is off will not receive generated Genius recommendations until a later
Sync with the setting enabled. Other Sync work remains subject to the same review,
validation, and transaction rules.
