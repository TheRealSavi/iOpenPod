# ADR-0044: Make Synesthesia topology and biography authoritative

- Status: Accepted
- Date: 2026-09-13
- Supersedes: The fixed Visual Motif path and OpenGL feedback implementation in
  ADR-0043

## Context

ADR-0042 made the immutable World Score the boundary for complete-song musical
understanding. ADR-0043 correctly required one continuous world, but its fixed
twelve-motif path and paired OpenGL feedback surfaces still made visual identity a
sequence of rendered appearances. Layering and retaining images could not establish
spatial causality, a traversable tunnel, or a physical consequence that remained
identifiable when its appearance changed.

The governing artistic test is continuity. One pressure event must alter one place,
and that alteration must remain the same scar while the viewer can read the world as
vascular, botanical, terrain, and finally cosmic. The cosmic reading must emerge
late and retrospectively; it must not arrive as a scene transition. Rendering
technology therefore cannot be the authority for world identity or history.

## Decision

`WorldScore` remains the immutable analysis boundary established by ADR-0042. A
renderer-neutral `WorldScoreConductor` samples its Musical Evidence in context and
translates it into typed World Conditions. Those conditions express causes and
intent, including continuous controls, pressure occurrences, interpretation intent,
and camera attention. They are not draw calls, shader parameters, or replacement
geometry.

A CPU-authoritative `PersistentWorld` owns the Persistent Topology and World
Biography. Stable node and branch identities define one connected, branching
tunnel. Accepted occurrences create causal records and propagate through graph
distance. The first proof embodies one selected pressure cause as elastic motion and
one lasting plastic scar. Interpretation changes may alter what that topology and
scar appear to be, but may not replace their identities or erase their causal
record.

The world publishes immutable `WorldFrame` values containing its topology,
biography, overlapping interpretation, and autonomous camera pose. Rendering
adapters derive geometry and materials from a World Frame; GPU resources are
disposable projections and never become the only copy of world state.
Interpretation policy and Rendering Adapters are mutable presentation choices. They
may change the world's reading and projection but may not mint, replace, or discard
topology identities or biographical consequences.

The first proof is intentionally limited to:

- one Persistent Topology;
- one selected pressure cause;
- one lasting scar;
- one delayed, overlapping vascular to botanical to terrain to cosmic
  reinterpretation; and
- one autonomous camera that moves through and attends to that topology.

The interpretation weights overlap so more than one reading can remain plausible.
Cosmic material influence begins before cosmic recognition, allowing the final
reveal to reframe forms that were already present. This is reinterpretation of one
world, not a playlist of scenes.

Transport changes are explicit. A Transport Epoch identifies one uninterrupted
traversal of the musical timeline. Events cross at most once within an epoch. A seek
starts a new epoch and re-anchors the conductor without synthesizing skipped events;
crossing the same musical cause again may add another causal record to the existing
scar but may not create a second world or scar. Pause freezes world time, pressure,
interpretation, and camera motion. Seeking and pausing preserve the World Biography.

The rendering adapter is a `QRhiWidget`. A PySide 6.11 feasibility spike on Windows
with Direct3D 11 verified the QRhi widget lifecycle, packaged QShader loading,
dynamic buffers, and a depth-tested indexed draw. The implementation derives a
swept tunnel mesh from each relevant World Frame and uses QRhi's native backend for
Direct3D 11 on Windows, Metal on macOS, and OpenGL on Linux. QRhi resources are
destroyed and recreated when the backend changes or the widget releases them.

## Consequences

- Continuity, causality, event idempotence, scar persistence, transport behavior,
  overlapping interpretation, and autonomous camera motion can be tested without a
  GPU.
- Renderer failure or recreation cannot erase topology or biography; a replacement
  renderer can project the same World Frame through another technique.
- Musical analysis stays independent of Qt rendering, and the renderer does not
  import analysis arrays, model objects, or provider dependencies.
- The initial implementation has real three-dimensional geometry, depth, and camera
  motion, but deliberately does not add more topologies, events, scars, scene
  presets, or effect catalogs before the continuity proof succeeds.
- Packaged QShader artifacts must remain reproducible from their shader sources, and
  QRhi's compatibility across Qt minor versions must be verified when PySide is
  upgraded.
- ADR-0043's continuous-world intent remains in force. Its fixed twelve-motif
  progression, `QOpenGLWidget`, PyOpenGL binding, and paired feedback surfaces are
  historical implementation choices rather than the current architecture.
