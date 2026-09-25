# ADR-0049: Choreograph Synesthesia Scenes as music-driven journeys

- Status: Accepted
- Date: 2026-09-13
- Extends: ADR-0048
- Camera policy extended by: ADR-0050

## Context

ADR-0048 introduced distinct procedural visual Scenes, but their first production
forms were still primarily screen-space compositions. Most time coefficients were
slow, Musical Evidence changed appearance more than motion, the shared field camera
barely moved, and temporal feedback retained marks without a common travel vector.
A still image could distinguish the Scenes, yet playback still read as animated
overlays rather than movement through a place.

The existing Track Analysis already carries enough continuous evidence to direct
motion. Adding raw waveform buffers or presentation choreography to the analysis
backend is unnecessary for this problem and would violate the analysis boundary.

## Decision

Extend each frontend `SceneCue` with typed `SceneMotion`. It contains a normalized
travel direction plus travel rate, orbit rate, depth velocity, waveform deformation
gain, parallax, and world scale. The Scene Director selects a distinct base motion
profile per visual Scene, scales it from the cue's Mood Signature, varies its heading
deterministically per Track, and interpolates it during Scene transitions.

The renderer publishes Scene Motion through two uniform vectors. The procedural
Scene and shared feedback consume the same choreography; camera policy is separated
by ADR-0050. Retained-light feedback advects along the same direction and applies a
small depth warp, allowing trails to reveal travel instead of remaining stuck to
the screen.

The procedural Scene shader constructs a musical deformation curve from current
energy, spectral brightness and flux, harmonic and percussive layers, rhythmic
pulse, beat phase, and accepted onset strength. This is an evidence-shaped visual
wave, not a claim that the backend exposes raw PCM samples. Every Scene uses it
inside geometry and combines it with a distinct journey:

- Magnetosphere performs orbital fly-bys through moving gravitational nuclei.
- Ribbon Cascade traverses layered ribbons whose paths deform with musical waves.
- Warp Tunnel advances rings and spokes toward a moving vanishing point.
- Mirror Wave travels through folded, beat-shaped contour geometry.
- Prismatic Veil passes between independently advancing translucent sheets.
- Lattice Cathedral moves forward through a perspective grid and approaching arches.
- Solar Bloom orbits and passes a displaced body with travelling pressure fronts.
- Star Chamber streams multiple parallax star layers past a moving dust horizon.

Pause continues to freeze field time, so autonomous motion stops with transport.
Seeking changes Musical Evidence without replacing the live field or replaying an
event backlog; the presentation clears view-dependent feedback at the new framing.

## Consequences

- Every Scene has explicit direction and depth behavior instead of relying on small
  elapsed-time phase changes.
- Musical Evidence affects displacement and velocity as well as color, density, and
  brightness.
- Shared particles, comets, and filaments move under a camera consistent with the
  procedural composition, reducing the impression of unrelated overlays.
- The uniform block grows by two `vec4` values and every portable shader package
  must share the new layout.
- True raw-waveform or oscilloscope rendering remains a separate future analysis
  decision; this change does not modify the backend contract.
