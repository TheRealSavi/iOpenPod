# ADR-0077: Hold Synesthesia Scenes across short Sections

- Status: Accepted
- Date: 2026-09-25
- Supersedes in part: ADR-0048's per-Section residence planning

## Context

The Scene Director treated every analyzed Section boundary as a Scene change.
Short Sections could therefore produce repeated crossfades before a composition
settled. Meanwhile the entire shared particle population remained visible at
moderate activity, letting particles and comet trails obscure the procedural Scene.

## Decision

Keep Track Analysis and its Section boundaries as Musical Evidence. Presentation
follows Section boundaries with a two-second minimum Scene hold. Only Sections
that would cause faster changes are grouped, including a final fragment shorter
than two seconds. There is no preferred residence duration: eligible musical edits
take precedence. Longer Sections retain the existing subdivision into cues of at
most 22 seconds, preserving their accepted boundaries. A Track shorter than two
seconds has one Scene. Cue planning remains deterministic, with continuous camera
bridges, recent-Scene diversity, and seek-stable sampling.

The Field Conductor continues to sample the current musical moment, so changes
inside a residence still affect the field and retain their typed events. Camera
Shot edits can also use musical punctuation without replacing the whole Scene.

The particle pass reveals a stable subset of the simulated population, expanding
smoothly as activity rises. Comet visibility also ramps gradually with activity,
while spectrum, percussion, and excitation retain their distinct appearance and
motion roles. Strong peaks retain the full visual range. Neither change discards
analysis evidence or resets particle simulation.

## Consequences

Scene selection follows musical structure while suppressing rapid flicker from
very short Sections. Sparse beginnings leave room for fuller particle fields later.
The CPU/GPU uniform layout and
analysis backend contract remain unchanged; portable particle and comet shader
packages must be regenerated.
